#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property, partial
import locale
from pathlib import Path
import re
import readline
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, Iterable, List, Mapping

warn = partial(print, file=sys.stderr)

INDEX_DIR = ".index"
DEFAULT_CATEGORY = "_toSort"
OCR_LANGS = [
    "deu",
    "eng",
]
DEFAULT_SCAN_SOURCE = "ADF Duplex"
ALTERNATE_SCAN_SOURCE = "Flatbed"
MIN_NUM_WIDTH = 6 # only used for INDEX_DIR files

def build_args(args: Iterable) -> str:
    return " ".join((shlex.quote(str(e)) for e in args))

def build_ocr_args(in_file: str, out_file: str, ocr_langs: Iterable[str] = OCR_LANGS, additional_args: Iterable = []) -> str:
    return build_args([
        "ocrmypdf",
        "--skip-text",
        "--pdfa-image-compression", "jpeg", # usable as only applied once
        "--jpeg-quality", "100", # ensure highest quality
        "-l", "+".join(ocr_langs),
        *additional_args,
        in_file,
        out_file,
    ])

def rlinput(prompt, prefill=None, suggestions=[]):
    if suggestions and prefill is None:
        prefill = suggestions.pop(0)
    readline.clear_history()
    for sug in reversed(suggestions):
        readline.add_history(sug)
    readline.set_startup_hook(lambda: readline.insert_text(prefill or ""))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook()

ID_REGEX = re.compile(r"""^
    (
        (?P<digital>d(igital)?) # no physical original
        |
        (
            (?P<id_simple>\d+) # simple id
            |
            (?P<id_following>\d+)\+ # id and following id
            |
            (?P<id_following_twice>\d+)\+\+ # id and following 3 ids (this and following document with each 2 sides)
            |
            (?P<id_range_begin>\d+)-(?P<id_range_end>\d+) # id range
        )(?P<around>\#)?
    )
$""", re.VERBOSE)
ID_AROUND_RANGE = 10

@dataclass(eq=True, order=True, frozen=True)
class IdRange:
    first: int
    last: int

    @classmethod
    def from_match(cls, m: re.Match):
        if not m:
            return None
        r = None
        if m.group("digital"):
            r = (-1, -1)
        elif m.group("id_simple"):
            id_first = int(m.group("id_simple"))
            r = (id_first, id_first)
        elif m.group("id_following"):
            id_first = int(m.group("id_following"))
            r = (id_first, id_first + 1)
        elif m.group("id_following_twice"):
            id_first = int(m.group("id_following_twice"))
            r = (id_first, id_first + 3)
        elif m.group("id_range_begin"):
            begin_str, end_str = m.group("id_range_begin"), m.group("id_range_end")
            common_prefix_len = len(begin_str) - len(end_str)
            different_suffix_len = len(begin_str) - common_prefix_len
            if common_prefix_len > 0:
                end_str = begin_str[0:common_prefix_len] + end_str
            begin_int, end_int = int(begin_str), int(end_str)
            if common_prefix_len > 0 and begin_int > end_int:
                end_int += 10 ** different_suffix_len
            r = (begin_int, end_int)
        else:
            return None
        if r[1] < r[0]:
            raise Exception(f"IdRange invalid, last < first, {r[1]} < {r[0]}, range: {r}")
        if m.group("around"):
            r = (r[0] - ID_AROUND_RANGE, r[1] + ID_AROUND_RANGE)
        return cls(*r)

    @classmethod
    def from_str(cls, s: str):
        return cls.from_match(ID_REGEX.match(s))

    @classmethod
    def from_scans(cls, scans):
        return cls(scans[0].id_range.first, scans[-1].id_range.last)

    @property
    def is_digital(self):
        return self.last < 0

    @property
    def fancy(self):
        return self.to_fancy()

    def to_fancy(self, width: int = 0):
        if self.first == self.last:
            return f"{self.first:0{width}}"
        if self.first == self.last - 1:
            return f"{self.first:0{width}}+"
        return f"{self.first:0{width}}-{self.last:0{width}}"

    def align(self):
        first = self.first
        if first % 2 == 0:
            first -= 1
        last = self.last
        if last % 2 == 1:
            last += 1
        return IdRange(first, last)

    def __format__(self, format_spec):
        return self.fancy.__format__(format_spec)

    def __iter__(self):
        return iter(range(self.first, self.last + 1))

    def __len__(self):
        return self.last - self.first + 1

    def __str__(self):
        return self.fancy


SCAN_SUFFIXES = [ # Regexes
    "jpe?g",
    "pdf",
    "png",
]

SCAN_REGEX = re.compile(r"""^
    ( # Date
        (?P<date>\d{4}-\d{2}-\d{2})_
    )?
    # automatic prefix of scanimage
    (out)?
    # scan id
    (?P<scan_id>
        """ + ID_REGEX.pattern[1:-1] + r"""
    )
    ( # Description (optional)
        _(?P<description>.*)
    )?
    # Suffix
    \.(""" + "|".join(SCAN_SUFFIXES) + r""")
$""", re.VERBOSE)
SCAN_WARN_REGEX = re.compile(r"\.(" + "|".join(SCAN_SUFFIXES) + r")$")

NUMBER_REGEX = re.compile(r"^\d+$")
CONTENT_SPLIT_REGEX = re.compile(r"[\W]")

DATE_REGEX = re.compile(r"(\d{2,4}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}\.\d{2,4}|\d{1,2}\.\s+[a-zA-Z]+\s+\d{2,4})")
DATE_FORMATS = [
    "%Y-%m-%d",
    "%y-%m-%d",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d. %B %Y",
    "%d. %B %y",
    "%d. %b %Y",
    "%d. %b %y",
]
def interpret_date(text: str) -> datetime:
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None
def format_date(date: datetime) -> str:
    return date.strftime(DATE_FORMATS[0])
def avg(dates: list[datetime]) -> datetime:
    m = min(dates)
    s = sum((date - m for date in dates), start=timedelta())
    return m + (s / len(dates))

@dataclass
class ScanFile:
    path: Path
    date: str
    id_range: IdRange
    description: str

    @classmethod
    def from_path(cls, path: Path):
        m = SCAN_REGEX.match(path.name)
        if not m:
            if SCAN_WARN_REGEX.search(path.name):
                warn(f"{path}: Seems like a scanned document, but name is invalid")
            return None
        date = m.group("date")
        id_range = IdRange.from_match(m)
        if not id_range:
            raise Exception(f"IdRange could not be found while SCAN_REGEX matched, SCAN_REGEX must be invalid!")
        desc = m.group("description")
        return ScanFile(path, date, id_range, desc)

    @property
    def first_id(self):
        return self.id_range.first

    @property
    def last_id(self):
        return self.id_range.last

    @property
    def is_digital(self):
        return self.id_range.is_digital

    @property
    def title(self):
        if self.description:
            return self.description
        return self.path.with_suffix("").name

    @property
    def title_or_content(self):
        if self.description:
            return self.description
        return ",".join(self.most_common_words[:6])

    @property
    def has_already_ocr(self) -> bool:
        return self.path.suffix == ".pdf"

    @cached_property
    def text_content(self) -> str:
        if self.has_already_ocr:
            cmd = [
                "pdftotext",
            ]
        else:
            cmd = [
                "tesseract",
                "-l", "+".join(OCR_LANGS),
            ]
        cmd += [
            str(self.path.resolve()),
            "-",
        ]
        proc = subprocess.run(cmd, shell=False, check=True, capture_output=True, text=True)
        return proc.stdout

    @property
    def autocomplete_content(self) -> list[str]:
        return [e for e in CONTENT_SPLIT_REGEX.split(self.text_content) if len(e) >= 3]

    @cached_property
    def most_common_words(self) -> list[str]:
        word_counter = dict()
        for word in self.autocomplete_content:
            if word in word_counter:
                word_counter[word] += 1
            else:
                word_counter[word] = 1
        return [item[0] for item in sorted(word_counter.items(), key=lambda item: item[1])]

    @cached_property
    def all_dates_from_content(self) -> list[datetime]:
        # TODO date https://stackoverflow.com/questions/7821661/how-to-code-autocompletion-in-python
        dates = set()
        for probable_date in DATE_REGEX.finditer(self.text_content):
            probable_date_filtered = re.sub(r"\s", " ", probable_date.group(0))
            date = interpret_date(probable_date_filtered)
            if date and date not in dates:
                dates.add(date)
        if len(dates) <= 1:
            return list(dates)
        older_dates = set()
        min_date = min(dates)
        max_date = max(dates)
        date_subset = dates - {min_date,}
        while len(date_subset) > 0 and max_date - min_date >= 2 * (max_date - min(date_subset)):
            dates = date_subset
            date_subset = dates - {min_date,}
            older_dates.add(min_date)
            min_date = min(dates)
        avg_date = avg(dates) + (max_date - min_date) * .2
        return sorted(dates, key=lambda date: abs(avg_date - date)) + sorted(older_dates, reverse=True)

    @property
    def date_from_content(self) -> str:
        dates = self.all_dates_from_content
        if dates:
            return format_date(dates[0])
        return None

    def gen_small_summary_entry(self):
        return [
            str(self.id_range),
            self.description or "",
        ]

    def gen_small_summary(self):
        return " ".join(self.gen_small_summary_entry())

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        return self.path == other.path

SCAN_FORMATS: dict[Callable[[ScanFile], str]] = {
    "content": lambda scan: scan.text_content,
    "date": lambda scan: scan.date_from_content,
    "id": lambda scan: str(scan.id_range),
    "id-date-title": lambda scan: f"{scan.id_range:>12}  {str(scan.date):<10}  {scan.title_or_content}",
    "id-path": lambda scan: f"{scan.id_range:>12}  {scan.path}",
    "id-title": lambda scan: f"{scan.id_range:>12}  {scan.title_or_content}",
    "path": lambda scan: scan.path,
    "title": lambda scan: scan.title_or_content,
}


def iter_files(path) -> Iterable[Path]:
    for child in Path(path).iterdir():
        if child.is_dir() and not child.name.startswith("."):
            for child_child in iter_files(child):
                yield child_child
        elif child.is_file():
            yield child

def iter_scans(path) -> Iterable[Path]:
    for scan_path in iter_files(path):
        scan_file = ScanFile.from_path(scan_path)
        if scan_file:
            yield scan_file

def iter_categories(path) -> Iterable[str]:
    for child in Path(path).iterdir():
        if child.is_dir() and not child.name.startswith(".") and not child.name.startswith("_"):
            yield child.name
            for child_child_name in iter_categories(child):
                yield f"{child.name}/{child_child_name}"

def sorted_by_id(scans) -> Iterable[ScanFile]:
    return sorted(scans, key=lambda scan: scan.first_id)

def highest_id(scans) -> int:
    return max(scans, key=lambda scan: scan.last_id).last_id

def resolve_per_id(scans):
    scans = list(scans)
    ids = [set() for i in range(highest_id(scans) + 1)]
    for scan in scans:
        if scan.is_digital:
            ids[0].add(scan)
        else:
            for i in scan.id_range:
                ids[i].add(scan)
    return ids

def next_id(scans) -> int:
    next_one = highest_id(scans)
    next_one += 1
    if next_one % 2 == 0:
        next_one += 1 # next id should be odd
    return next_one

def lookup_scans(scans, *id_ranges):
    scan_ids = resolve_per_id(scans)
    return {scan for id_r in id_ranges for i in id_r if i < len(scan_ids) for scan in scan_ids[i]}

def extract_dates(scans: List[ScanFile]) -> List[str]:
    # used dict instead of set to gurantee input order
    dates: Mapping[str, None] = dict()
    for scan in scans:
        if scan.date:
            dates[scan.date] = None
    for scan in scans:
        for date in scan.all_dates_from_content:
            dates[format_date(date)] = None
    return list(dates)

# args dependent

def read_single_id(args):
    if not args.id:
        warn("--id missing")
        sys.exit(2)
    id_r = IdRange.from_str(args.id)
    if id_r is None:
        warn(f'id "{args.id}" is invalid')
        sys.exit(2)
    return id_r

def read_ids(args):
    if not args.id:
        warn("--id missing")
        sys.exit(2)
    ids_str = args.id.split(",")
    for id_str in ids_str:
        id_r = IdRange.from_str(id_str)
        if id_r is None:
            warn(f'id "{id_str}" is invalid')
            sys.exit(2)
        yield id_r

def print_scans(args, scans, do_view=True):
    f = SCAN_FORMATS[args.format]
    for scan in scans:
        print(f(scan))
    if do_view and args.view:
        proc = subprocess.Popen(["imv-x11", *(str(scan.path) for scan in scans)], stdin=None, stdout=None, stderr=None, close_fds=True)
        return lambda: proc.terminate()
    return lambda: None

def cmd_by_id(args, scans):
    id_ranges = read_ids(args)
    print_scans(args, sorted_by_id(lookup_scans(scans, *id_ranges)))

def cmd_check_duplicates(args, scans):
    print_anything = False
    ids = resolve_per_id(scans)
    ids.pop(0) # remove digital only
    for id_scans in ids:
        if 1 < len(id_scans):
            if print_anything:
                print("---")
            print_anything = True
            print_scans(args, id_scans)
    if print_anything:
        sys.exit(1)

def cmd_convert(args, scans: Iterable[ScanFile]):
    cmd_list = list[str]()
    for scan in scans:
        if not scan.has_already_ocr:
            cmd_list.append("&&".join([
                build_ocr_args(scan.path, out_file=scan.path.with_suffix(".pdf"), additional_args=["--jobs", "1"]),
                build_args([
                    "rm",
                    scan.path,
                ]),
            ]))
    if args.output_commands:
        for cmd in cmd_list:
            print(cmd)
    else:
        for cmd in cmd_list:
            subprocess.run(cmd, check=True, shell=True)

def cmd_list(args, scans):
    print_scans(args, sorted_by_id(scans))

def cmd_list_categories(args, scans):
    for category in iter_categories("."):
        print(category)

def cmd_merge(args, scans):
    # search for scans
    id_r = read_single_id(args).align()
    found = sorted_by_id(lookup_scans(scans, id_r))
    if len(found) <= 0:
        warn(f"No scan with id {id_r} found")
        sys.exit(3)
    elif len(found) == 1 and found[0].path.suffix == ".pdf" and found[0].date is not None:
        warn(f"Only one scan with {id_r} found which is already a PDF and has a date, so no merge required")
        sys.exit(4)
    id_r = IdRange.from_scans(found)
    if len(id_r) > 2:
        id_r = id_r.align()
    print("will merge following scans:")
    print_scans(args, found, do_view=False)
    print("")
    # combine before for better displayment
    def build_cmd(output_file: Path):
        combine_args = build_args([
            "pdfunite",
            *(scan.path for scan in found),
            "/dev/stdout",
        ])
        ocr_args = build_ocr_args("-", output_file)
        return f"{combine_args} | {ocr_args}"
    with tempfile.NamedTemporaryFile() as fp:
        subprocess.run(build_cmd(fp.name), check=True, shell=True)
        if args.view:
            pdf_viewer = subprocess.Popen(["zathura", "--mode=fullscreen", fp.name], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        # get existing parameters
        doc_dates = [format_date(datetime.now())] + extract_dates(found)
        doc_dates = [] + doc_dates
        doc_title = ""
        for scan in found:
            if scan.description:
                doc_title = scan.description
                break
        doc_categories = sorted(iter_categories("."), key=locale.strxfrm)
        # ask for doc date, description, category for output_file
        doc_date = rlinput("Document date: ", suggestions=doc_dates)
        doc_title = rlinput("Document title: ", doc_title)
        doc_category = rlinput("Document category: ", prefill="", suggestions=doc_categories) or DEFAULT_CATEGORY
        output_file = str(id_r)
        if doc_date:
            output_file = f"{doc_date}_{output_file}"
        if doc_title:
            output_file += f"_{doc_title}"
        output_file = f"{doc_category}/{output_file}.pdf"
        if args.view:
            pdf_viewer.terminate()
        # execute command
        if args.dry_run:
            print(build_cmd(output_file))
            return
        cat_dir = Path(doc_category)
        if not cat_dir.is_dir():
            cat_dir.mkdir(parents=True)
        Path(fp.name).rename(output_file)
        Path(fp.name).touch()
        if not args.keep:
            for scan in found:
                scan.path.unlink()

def cmd_missing_ids(args, scans):
    ids = resolve_per_id(scans)
    ids.pop(0) # remove digital only
    for i, id_scans in enumerate(ids):
        if (i % 2) == 0: # odd ids when i is even due to .pop(0)
            if len(id_scans) <= 0:
                print(f"{i + 1}+") # due to .pop(0)

def cmd_next_id(args, scans):
    print(args.force_next_id or next_id(scans))

def cmd_rebuild_index(args, scans: Iterable[ScanFile]):
    index_dir = Path(INDEX_DIR)
    if index_dir.exists():
        if not index_dir.is_dir():
            raise Exception(f"Expected '{index_dir}' to be a directory or to not exist")
        shutil.rmtree(index_dir)
    index_dir.mkdir()
    scans = list(scans)
    num_width = max(len(str(highest_id(scans))), MIN_NUM_WIDTH)
    for scan in scans:
        if not scan.is_digital:
            (index_dir / f"{scan.id_range.to_fancy(width=num_width)}_{scan.title}{scan.path.suffix}").symlink_to(".." / scan.path.relative_to(index_dir.parent))

def cmd_scan(args, scans):
    scans = list(scans)
    cmd = [
        "scanimage",
        "--source", ALTERNATE_SCAN_SOURCE if args.flatbed else DEFAULT_SCAN_SOURCE,
        "--batch",
        "--batch-start", str(args.force_next_id or next_id(scans)),
        "--batch-print",
        "--format", "png",
        "--resolution", "600",
    ]
    if args.flatbed:
        cmd.append("--batch-prompt")
    subprocess.run(cmd, check=True, cwd=Path(DEFAULT_CATEGORY).resolve())
    if not args.skip_convert:
        cmd_convert(args, scans)

def cmd_test_id_align(args, scans):
    tests = [
        (IdRange(1, 2), IdRange(1, 2)),
        (IdRange(1, 3), IdRange(1, 4)),
        (IdRange(4, 4), IdRange(3, 4)),
        (IdRange(4, 8), IdRange(3, 8)),
        (IdRange(4, 7), IdRange(3, 8)),
    ]
    for test in tests:
        aligned = test[0].align()
        if aligned != test[1]:
            warn(f"{test[0]} aligned to {aligned} does not equal to {test[1]}")
            sys.exit(1)

COMMANDS = {
    "by-id": cmd_by_id,
    "check-duplicates": cmd_check_duplicates,
    "convert": cmd_convert,
    "list-categories": cmd_list_categories,
    "merge": cmd_merge,
    "missing-ids": cmd_missing_ids,
    "next-id": cmd_next_id,
    "rebuild-index": cmd_rebuild_index,
    "scan": cmd_scan,
    "test-id-align": cmd_test_id_align,
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--dry-run", "--simulate", action="store_true")
    parser.add_argument("--force-next-id", required=False)
    parser.add_argument("-k", "--keep", action="store_true")
    parser.add_argument("-F", "--flatbed", action="store_true")
    parser.add_argument("-f", "--format", choices=list(SCAN_FORMATS), default="id-date-title")
    parser.add_argument("--id", "--ids", required=False)
    parser.add_argument("--view", action="store_true")
    parser.add_argument("--output-commands", action="store_true")
    parser.add_argument("--skip-convert", action="store_true")
    parser.add_argument("action", choices=list(COMMANDS))
    args = parser.parse_args()
    scans = iter_scans(".")
    try:
        COMMANDS[args.action](args, scans)
    except subprocess.CalledProcessError as e:
        warn(f"Failed to run command, exited with exit code {e.returncode}: " + " ".join(e.cmd) if type(e.cmd) == list else e.cmd)
        sys.exit(2)
    except KeyboardInterrupt:
        print("Aborted by user")
        sys.exit(1)

if __name__ == "__main__":
    main()
