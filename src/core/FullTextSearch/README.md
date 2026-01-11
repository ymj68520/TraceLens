# FullTextSearch Module

Full-text indexing and search capabilities for the Forensics Project using Xapian.

## Features

- **Xapian-based indexing**: Fast, full-text search with stemming support
- **Multi-language support**: Configurable stemmer for different languages
- **Snippet generation**: Context-aware search result snippets with term highlighting
- **Metadata indexing**: Index file size, extension, and modification time
- **Binary string extraction**: Extract readable strings from binary files
- **90+ file type support**: Extensive text file type recognition

## Components

### XapianIndexer
Indexes file content into a Xapian database.

```cpp
forensics::XapianIndexer indexer("/path/to/index_db");
indexer.addDocument("/path/to/file.txt", "file content here");
indexer.commit();
```

### XapianSearcher
Searches indexed documents with support for:
- Boolean operators (AND, OR, NOT)
- Wildcards (term*)
- Path prefix search (`path:/home/...`)
- Extension filtering (`ext:.txt`)

```cpp
forensics::XapianSearcher searcher("/path/to/index_db");
auto results = searcher.search("forensics AND analysis", 10, 0);
for (const auto& r : results) {
    std::cout << r.path << " (" << r.score << "%): " << r.snippet << std::endl;
}
```

### TextExtractor
Extracts text content from files based on type.

```cpp
std::string content = forensics::TextExtractor::extract("/path/to/file.log");
bool isText = forensics::TextExtractor::isTextFile(".cpp");
auto meta = forensics::TextExtractor::extractMetadata("/path/to/file.txt");
```

## CLI Usage

### Index a directory
```bash
./forensic_analyzer --index /path/to/directory --db-dir /path/to/output
```

### Search the index
```bash
./forensic_analyzer --search "keyword" --db-dir /path/to/output
```

## Supported Text Extensions

The TextExtractor recognizes 90+ text file extensions including:
- Plain text: `.txt`, `.log`, `.csv`
- Configuration: `.ini`, `.yaml`, `.json`, `.toml`
- Web: `.html`, `.css`, `.js`, `.ts`
- Programming: `.c`, `.cpp`, `.py`, `.java`, `.go`, `.rs`
- Scripts: `.sh`, `.bat`, `.ps1`
- Documentation: `.md`, `.rst`, `.tex`
- Data: `.sql`, `.graphql`

## Dependencies

- **Xapian**: Full-text search engine library
- **C++17 filesystem**: For file operations
