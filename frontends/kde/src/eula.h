#pragma once

// The terms-of-use page (shared/flow/screens.yaml `eula`): where the file
// lives and how its sections reach QML.
//
// One shared path for every frontend: /usr/share/tuna-installer/eula.xml
// (an AppStream agreement of type `eula`). TUNA_EULA_FILE overrides it for
// tests and demos. No file skips the page.
#include <QList>
#include <QString>
#include <QStringList>
#include <QVariantList>

namespace eula
{

// Test seam: the EULA file to read instead of the shared path.
inline constexpr const char *FILE_ENV = "TUNA_EULA_FILE";

// The EULA file, or empty when none is installed.
QString findFile();

// One paragraph or one list, in document order.
struct Block {
    enum class Kind { Paragraph, List };
    Kind kind = Kind::Paragraph;
    QString text; // the paragraph, or "" for a list
    QStringList items; // the list entries, or empty for a paragraph
    bool ordered = false; // numbered entries when true
};

struct Section {
    QString heading; // empty when the file names none
    QList<Block> blocks;
};

struct Document {
    bool ok = false;
    QString error; // why the file could not be read; empty when ok
    QList<Section> sections;
};

// AppStream agreement sections (paragraphs, ordered and unordered lists)
// when the file is XML, else the whole text as one paragraph block per
// blank-line-separated stanza.
Document read(const QString &path);

// The document as QML renders it: [{heading, blocks:
// [{kind: "p" | "ul" | "ol", text, items}]}].
QVariantList toVariant(const Document &document);

} // namespace eula
