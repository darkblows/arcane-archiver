# 🏺 ArcaneForumArch
> **vBulletin Data Scraper, Media Mirroring & Persistence Engine**

[![Python](https://img.shields.io/badge/Python-3.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Environment](https://img.shields.io/badge/OS-Windows%20%7C%20Linux-blueviolet.svg)](#)

Automated framework for recursive extraction, parsing, and serialization of vBulletin-based forum instances. This software implements an asynchronous processing pipeline to ensure local persistence of threads, metadata, and multimedia assets.

---

<img width="1096" height="962" alt="Screen" src="https://github.com/user-attachments/assets/2b09b20f-5c4b-4f18-8975-a2b67f206162" />


## ⚙️ Technical Architecture

### 1. 🔍 Crawling Engine & DOM Parsing
The core is built upon a heuristic scanning system for vBulletin hierarchies.
* **Recursive Depth Control:** Scan depth management via CSS selector parsing and URL constant tracking (`threadid`, `postid`, `page`).
* **RegEx Pattern Matching:** Path sanitization and automatic stripping of session tokens and redundant parameters to prevent infinite loops and data duplication.
* **In-Memory Deduplication:** Implementation of hashing sets to track processed endpoints (`visited`/`pending`).



[Image of a web crawler architecture diagram]


### 2. 💾 I/O Management & Media Mirroring
Specialized module for asset reconstruction to facilitate full offline navigation.
* **Dynamic Relative Mapping:** On-the-fly conversion of `src` and `href` attributes from remote endpoints to local filesystem paths.
* **MIME-Type Validation:** Automated file extension verification via HTTP header analysis, ensuring the integrity of downloaded assets (images, avatars, attachments).
* **Binary Persistence:** Asynchronous disk-write pipeline to prevent Main Thread blocking during massive data ingestion.

### 3. 📊 Serialization & Data Transformation
* **JSON Schema:** Structured data export (author, timestamp, content, forum hierarchy) into JSON format for external database integration or computational analysis.
* **HTML Mirroring:** Frontend reconstruction through local templating, maintaining original thread coherence without external dependencies.

### 4. 🧠 Resource Management & Concurrency
* **Multi-threading:** Execution of download and crawling processes on separate daemon threads to maintain Tkinter UI responsiveness.
* **Manual Garbage Collection:** Cyclic invocation of `gc.collect()` and BeautifulSoup buffer flushing to mitigate memory leaks during large-scale scans (10k+ posts).

---

## 🛠 Binary Compilation

### 🐧 Linux (x86_64 Architecture)
Ensure `python3-tk` and kernel development headers are installed on the host system.

```bash
pyinstaller --noconfirm --onefile --windowed \
--name "ArcaneArchiver" \
--icon "icon.png" \
--collect-all tkinter \
--collect-submodules requests \
--collect-submodules bs4 \
--hidden-import PIL._imagingtk \
--hidden-import PIL._tkinter_finder \
"ArcaneForumArch.py"


### 🪟 Windows (x86_64 Architecture)

```bash
wine python -m PyInstaller --noconfirm --onefile --windowed \
--icon "icon.png" \
--name "ArcaneArchiver_Win" \
--collect-all tkinter \
--collect-all requests \
--collect-all bs4 \
--hidden-import PIL._imagingtk \
--hidden-import PIL._tkinter_finder \
"ArcaneForumArch.py"
