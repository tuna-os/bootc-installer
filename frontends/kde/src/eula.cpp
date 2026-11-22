#include "eula.h"

#include <QCoreApplication>
#include <QFile>
#include <QXmlStreamReader>

namespace eula
{

QString findFile()
{
    // One shared path for every frontend, TUNA_EULA_FILE winning for tests
    // and demos. No file skips the page.
    const QString override = qEnvironmentVariable(FILE_ENV);
    if (!override.isEmpty())
        return override;
    const QString shared = QStringLiteral("/usr/share/tuna-installer/eula.xml");
    if (QFile::exists(shared))
        return shared;
    return {};
}

namespace
{
QString readTextFile(const QString &path, QString *error)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        *error = QCoreApplication::translate("eula", "the terms of use cannot be read");
        return {};
    }
    return QString::fromUtf8(file.readAll());
}

// Reads <p> and <li> text: character data with inner tags skipped.
QString readInlineText(QXmlStreamReader &xml)
{
    QString out;
    while (!xml.atEnd()) {
        xml.readNext();
        if (xml.isCharacters())
            out += xml.text();
        else if (xml.isEndElement())
            break;
    }
    return out.trimmed();
}

// One <ul> or <ol>: its <li> entries.
Block readList(QXmlStreamReader &xml, bool ordered)
{
    Block block;
    block.kind = Block::Kind::List;
    block.ordered = ordered;
    const QString listName = xml.name().toString();
    while (!(xml.isEndElement() && xml.name() == listName) && !xml.atEnd()) {
        xml.readNext();
        if (xml.isStartElement() && xml.name() == QLatin1String("li")) {
            const QString item = readInlineText(xml);
            if (!item.isEmpty())
                block.items << item;
        }
    }
    return block;
}

// One <agreement_section>: its <name> heading and the <p>/<ul>/<ol> blocks.
Section readSection(QXmlStreamReader &xml)
{
    Section section;
    const QString sectionName = xml.name().toString();
    while (!(xml.isEndElement() && xml.name() == sectionName) && !xml.atEnd()) {
        xml.readNext();
        if (!xml.isStartElement())
            continue;
        const QStringView name = xml.name();
        if (name == QLatin1String("name"))
            section.heading = xml.readElementText().trimmed();
        else if (name == QLatin1String("p")) {
            const QString text = readInlineText(xml);
            if (!text.isEmpty()) {
                Block block;
                block.kind = Block::Kind::Paragraph;
                block.text = text;
                section.blocks.append(block);
            }
        } else if (name == QLatin1String("ul") || name == QLatin1String("ol")) {
            Block block = readList(xml, name == QLatin1String("ol"));
            if (!block.items.isEmpty())
                section.blocks.append(block);
        }
    }
    return section;
}

Document readAgreement(QXmlStreamReader &xml)
{
    Document document;
    document.ok = true;
    while (!xml.atEnd()) {
        xml.readNext();
        if (xml.isEndElement() && xml.name() == QLatin1String("agreement"))
            break;
        if (xml.isStartElement() && xml.name() == QLatin1String("agreement_section"))
            document.sections.append(readSection(xml));
    }
    if (xml.hasError()) {
        document.ok = false;
        document.error =
            QCoreApplication::translate("eula", "the terms of use cannot be read");
        document.sections.clear();
    }
    return document;
}

Document readPlainText(const QString &text)
{
    Document document;
    document.ok = true;
    Section section;
    // Stanzas are blank-line-separated paragraphs.
    QString current;
    auto flush = [&] {
        const QString trimmed = current.trimmed();
        if (!trimmed.isEmpty()) {
            Block block;
            block.kind = Block::Kind::Paragraph;
            block.text = trimmed;
            section.blocks.append(block);
        }
        current.clear();
    };
    for (const QString &line : text.split(QLatin1Char('\n'))) {
        if (line.trimmed().isEmpty())
            flush();
        else {
            if (!current.isEmpty())
                current += QLatin1Char('\n');
            current += line;
        }
    }
    flush();
    document.sections.append(section);
    return document;
}
} // namespace

Document read(const QString &path)
{
    if (path.isEmpty())
        return {};
    QString error;
    const QString text = readTextFile(path, &error);
    if (!error.isEmpty()) {
        Document document;
        document.error = error;
        return document;
    }
    if (text.trimmed().startsWith(QLatin1Char('<'))) {
        // An AppStream agreement of type `eula` (the shared contract);
        // other agreements are not terms of use.
        QXmlStreamReader xml(text);
        while (!xml.atEnd()) {
            xml.readNext();
            if (xml.isStartElement() && xml.name() == QLatin1String("agreement")
                && xml.attributes().value(QLatin1String("type")) == QLatin1String("eula"))
                return readAgreement(xml);
        }
        // XML but no EULA agreement: nothing terms-like in it.
        Document document;
        document.error = QCoreApplication::translate("eula", "the terms of use cannot be read");
        return document;
    }
    return readPlainText(text);
}

QVariantList toVariant(const Document &document)
{
    QVariantList sections;
    for (const Section &section : document.sections) {
        QVariantList blocks;
        for (const Block &block : section.blocks) {
            if (block.kind == Block::Kind::Paragraph) {
                blocks.append(QVariantMap{{QStringLiteral("kind"), QStringLiteral("p")},
                                          {QStringLiteral("text"), block.text}});
            } else {
                blocks.append(QVariantMap{{QStringLiteral("kind"), block.ordered ? QStringLiteral("ol") : QStringLiteral("ul")},
                                          {QStringLiteral("items"), block.items}});
            }
        }
        sections.append(
            QVariantMap{{QStringLiteral("heading"), section.heading}, {QStringLiteral("blocks"), blocks}});
    }
    return sections;
}

} // namespace eula
