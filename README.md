# scansystem

scansystem is a single file Python script to maintain (hence its script name) a directory containing your personal documents as PDFs.
It helps you with scanning them, applying OCR and sorting them based on categories you make up as you like.
It assigns incremental IDs to scanned documents which can help in finding

This script runs "stateless" without a database (everything required is encoded in human readable filenames or stored inside the PDFs itself).
So in contrast to other, more complex tools this script may provide this unique features to you:

- You do not need to use this script to access your documents, resorting them or even adding new ones. It is built to be just a small helper.
- It's compatible with every file synchronization solution (a.k.a. cloud) and backup solution you already have and might want to use in the future.
- You can use the tools you want to search through your documents (like `pdfgrep` or Recoll)
- You can use it without first configuring a server or anything similar.
- If this script stops working for you (for any reason), you can just continue on with your life without it.
- You can use the script (only) from the terminal.

Other features:

- It can combine multiple sides / pages into a single PDF which results in a single PDF having multiple IDs (ID per side) assigned.
- For "special documents" (or if your scanner is not capable of [ADF][wiki-adf]) you can use an interactive mode (provided by scanimage)
- It also "supports" digital only documents (but for now the do not have any IDs)


## Disclaimer

**Please check the known issues before using!**

I started this project for my own personal needs.
Because I have no problem sharing or working on it with others,
I decided to publish it on [GitHub][self-github] and mirror it to my [own Gitea instance][self-gitea].
However, especially for the first versions, it might not fit your use case and is hard to change.
So before using this script, check if it fits your needs.
It may help you to read my own use case described below.

This idea might not be a new, innovative solution, however I did not found any comparable solution which fit my use case.
If you find other solutions which you deem better for you, use them.
I would also be happy to know about them and have no problem listing them below for comparison.
Create an issue or PR if you might propose a similar project which should be listed below.


## Known Issues / ToDo

I know about these limitiations and I (or you) might resolve these in the future:
- Because of dependencies, it only works on UNIX so far.
- It assumes that your scanner will scan and return both sides of a scanned paper.
- Digital only documents for now have no IDs assigned.
- Ultimately, all scanned documents will be compressed with JPEG, but in a reasonable quality
- It is not really aware of the sorting of the paper documents, it just manages the IDs for now.
- Its configuration is "hard-coded" in the script making updating harder.
- The index will not be maintained automatically.
- The default configuration reflects my own and maybe are not sane defaults.
- It uses the current directory to determine the location of your documents. If executed from another directory, it might access other files and store scans elsewhere.


## How It Works (TL;DR)

Essentially system works as follows:
- each incomming page of a paper document will be scanned immediatally and be assigned an unique and incrementing ID, which is encoded in the filename
    - odd IDs indicate the front side of a page, even IDs indicate the back side of a page
    - meaning the sides from ID 1 to 200 reference 100 pages of paper
- the documents will be inserted in order of the IDs into binders
- each binder is labelled with the first and last IDs it holds
    - the binders can also be split by separators to find paper documents faster
- it is NOT required to label each document because of insertion order
    - this allows to preserve the original without modification (like a label)
    - this speeds up the insertion of 100's of pages a lot (assuming [ADF][wiki-adf] scanner)


## How To Use

### Preperations

You need:
- a [SANE][sane-web] compatible scanner or printer (see [list of supported devices][sane-supported])
    - scanner with [ADF][wiki-adf] is highly recommended
    - the feature to scan both sides automatically is also recommeded
    - however manual scanning with a flatbed is already supported
- empty ring binders
- a hole punch
- (optionally) plastic wraps for important paper documents which you might not want to hole punch

On your computer following tools should be installed (hopefully available in your distributions repository):
- [ocrmypdf][ocrmypdf-github] and its dependencies
    - could also call `tesseract` directly
- [parallel][parallel-web] (GNU variant, optional)
- utils from [poppler][poppler-web]
    - `pdftotext`
    - `pdfunite`
- utils from [SANE][sane-web]
    - `scanimage`

### First Setup

1. Set up at least one binder
    - label the binder with the range of IDs it will contain (starting at 1 for the first binder & section)
    - (optionally) each binder should have separators which you can label with the IDs they (will) contain
2. Create a directory on your computer for your scanned PDFs and copy the `./maintain.py` script into it
    - make it executable with `chmod +x ./maintain.py`
    - you can already create the sub directories for the categories (which can be nested as well), however you can also create them dynamically
3. Customize the configuration to your liking
    - for now, the configuration is stored inside the script at the beginning
    - especially configure the scan sources of your scanner (`USE_ADF_BY_DEFAULT` / `ADF_SCAN_SOURCE` / `FLATBET_SCAN_SOURCE`)
4. Migrate your old documents into the system by applying the steps below per document / page
    - the order is irrelevant, I recommend in chronical order as future documents will be inserted in the same order

#### Example

- I decided to hold up to 300 pages (600 sides or IDs) per binder
- Each binder is separated by separators into 6 sections containing each 50 pages (100 sides or IDs)
- If a document will span multiple sections or binders but is separated, I will still insert it correctly because I honor my system more than the "integrity" of the document

### How To Add New Documents

I recommend to follow the steps one by one per page at the beginning so the order does not get messed up.
If you feel safe, you can start to batch the tasks if you insert multiple pages at once.

*I seperate each document into its pages so it can be scanned automatically if possible, I even remove staples if required.*

Per page:
1. Scan both sides with `./maintain.py scan`
    - really either scan both sides or recall `./maintain.py scan` after each page because otherwise `scanimage` will mess up the IDs as it is not aware that the ID pairs should match front & back page
    - with `--adf` you can force use [ADF][wiki-adf] and it will continue to scan all pages available
    - with `--flatbed` you can force use the flatbed (e.g. for "special" documents)
    - by default, it will automatically apply OCR and convert the documents to PDFs
        - to speed up conversion of multiple pages by using parallel, add `--skip-convert` and execute `./maintain.py convert --output-commands | parallel` after scanning
    - after scanning, you might remove empty back pages, the script will still select the next ID correctly (see `./maintain.py next-id`)
2. Add ring holes using a hole punch if required
    - OR insert document into a plastic wrap with ring holes
3. Insert document into the latest binder at the end
    - Check on the IDs assigned if you want to place the document behind the next separator or in the next binder

### How To Sort & Combine

Per default, the documents are called `outXXXX.jpg` or `outXXXX.png`.
If you want to add date & title to your document or sort it into a category,
you can use `./maintain.py merge --id <IDs>`.
`<IDs>` might be a comma separated list of IDs which can be
- a single ID, e.g. `123`
- a single ID with its counterpart ID (the other side), suffix `+`, e.g. `453+,88+` == `453,454,87,88`
- a single ID with its following page, suffix `++`, e.g. `869++` == `869+,871+` == `869,870,871,872`
- an ID range, start and end separated by `-`, e.g. `123-128` == `123,124,125,126,127,128`
- a suffix of `#` (compatible to `+`, `++` and ranges) will also select all "context pages", by default ±10 pages, e.g. `100#` == `90-110` (not useful for merge but for other commands)
The order of the IDs will determine the order of the pages later on. However for merge:
- single IDs will be completed to both sides so both sides end up in the same PDF at the end
- missing IDs will be ignored (so missing back pages might not cause any error)
You can append `--view` so you will see the resulting document to verify.
If you abort the process before answering the last question, e.g. by using `CTRL+C`, nothing will be changed.

First, it asks for the date of the document.
By default, the current date will be proposed.
By using the arrow keys, you can select one of all dates found inside the document.

Second, it asks for the title of the document.
To assist you, the most used words per page will be displayed above.
Because each side has its own ID and each document its own date, the titles are not required to be unique.
I even recommend using the same title for documents of the same kind.

At last, it asks you where to put the document to.
If one document was already sorted into a category, it will proposed.
You can browse through all categories using the arrow keys and search through them using `CTRL+R`.

Because no database is held, you can rename the files manually as well.


## My Use Case

I am kind of a perfectionist and a lazy person,
which resulted in that I throwed every paper document I received in a single ring binder.
I did not came up with a "perfect" list of categories and how to distribute them accross different binders to
- minimize space (binders) required to hold all (important) documents
- allow each category to allow all documents which I might receive in future
- be able to find a required document quickly

Also I want all my documents to be accessable on all my devices.
This is easy to accomplish with already digital documents,
however our world requires real paper documents, especially in Germany.
So I wanted to scan every document to be able to store them on my personal cloud.
However the documents there would also be required to be sorted approriatly.
At least the digital world has the advantage that resorting documents in new categories scales a lot better and might also be automatable.
But still, this would require me to keep both worlds, the analog and the digital world sorted which means more work.

To solve both problems in an easy way,
I introduced a system to "store" all my paper documents in binders so I only need to sort them in the digital world.
If I then might need the original paper document, I can search for the desired document on my computer and look up where it is stored.


## Other Projects

- see [Awesome-Selfhosted][awesome-selfhosted]


<!-- References (sorted alphabetically) -->

[awesome-selfhosted]: https://github.com/awesome-selfhosted/awesome-selfhosted#document-management= "Document Management on Awesome-Selfhosted"
[ocrmypdf-github]: https://github.com/jbarlow83/OCRmyPDF "OCRmyPDF on GitHub"
[parallel-web]: https://www.gnu.org/software/parallel/ "GNU's parallel"
[poppler-web]: https://poppler.freedesktop.org/ "Poppler"
[sane-supported]: http://www.sane-project.org/sane-supported-devices.html "SANE - Supported Devices"
[sane-web]: http://www.sane-project.org/ "SANE - Scanner Access Now Easy"
[self-gitea]: https://git.banananet.work/zocker/scansystem "Self-Hosted Gitea Mirror"
[self-github]: https://github.com/Zocker1999NET/scansystem "Official GitHub Repository"
[wiki-adf]: https://en.wikipedia.org/wiki/Automatic_document_feeder "Automatic document feeder on Wikipedia"
