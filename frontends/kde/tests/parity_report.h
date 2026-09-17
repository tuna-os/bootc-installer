// Emit `walkthrough-<flavor>.json` — the file tunaOS's installer parity matrix
// consumes.
//
// WHY THIS EXISTS. tunaOS defines the screen contract once, in
// `tests/installer-screens.yaml`, and `scripts/installer-walkthrough.py` fills
// the parity matrix in `docs/INSTALLER-FRONTENDS.md` from a
// `walkthrough-<flavor>.json` per frontend. That harness boots a VM and OCRs
// QEMU screendumps, so it needs a virgl-capable host, and the matrix has sat on
// `_GPU_` / `_pending_` rows for the frontends nobody could measure.
//
// This emits the SAME file from the offscreen capture that already runs on a
// stock CI runner. No new contract and no new mechanism: the screenshots we
// already take, re-reported in the shape the matrix already reads.
//
// HOW IT DIFFERS FROM THE VM HARNESS, stated so nobody reads more into the
// numbers than is there:
//
//   * Text comes from the ITEM TREE, not OCR (`"ocr": false`,
//     `"text_source": "qml-item-tree"`). Stronger evidence for keyword matching
//     — no recognition error — and weaker evidence that a human could read it.
//     The pixel audit is what covers the latter, per page, as `rendered`.
//   * `activation_key` is null. Pages are driven by navigateTo(), so this run
//     says NOTHING about keyboard navigation. The defect the VM harness found
//     here — enter activates no button, tuna-installer-kde#4 — is invisible to
//     this harness by construction and must stay the VM run's job.
//   * `frames` are wizard pages, one apiece, not timed samples of a live VM.
//
// The metrics, thresholds and the rule about which screens may be credited are
// deliberately identical to `scripts/installer-walkthrough.py`, so numbers from
// the two sources mean the same thing.

#pragma once

#include <QAbstractButton>
#include <QFile>
#include <QGroupBox>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QPlainTextEdit>
#include <QSet>
#include <QString>
#include <QStringList>
#include <QTextEdit>
#include <QTextStream>
#include <QVector>
#include <QWidget>

namespace parity {

// Same values as scripts/installer-walkthrough.py in tuna-os/tunaOS.
constexpr double kBlankStddev = 0.02; // grayscale stddev floor for "blank"
constexpr int kDiffPixels = 500;      // pixels that must change for a transition

struct Screen {
    QString id;
    bool required;
    QStringList keywords;
};

// Copied VERBATIM from tuna-os/tunaOS `tests/installer-screens.yaml`.
// Duplicated rather than fetched so the capture stays hermetic on a runner with
// no network — which does make drift possible in the one place it would be most
// embarrassing. The Python siblings (tuna-installer-xfce, tuna-installer-niri)
// re-check their copy against the upstream file at runtime and warn on a
// mismatch; doing the same here would mean linking QtNetwork into the capture
// for one HTTP GET, so this copy is instead checked by the workflow step below
// — same warning, no new link dependency.
//
// The upstream comments are load-bearing and are kept: each one explains a
// keyword that PREVIOUSLY produced a false row in the matrix.
inline QVector<Screen> spec()
{
    return {
        // No product-name keyword. Upstream removed "install tunaos" in
        // tuna-os/tunaOS#1060: the frontends now substitute the VARIANT name
        // from os-release ("Install Skipjack"), so a keyword containing
        // "tunaos" matches only the fallback build and reports a missing
        // welcome screen on every real variant ISO.
        {QStringLiteral("welcome"), true,
         {QStringLiteral("welcome"), QStringLiteral("get started"),
          QStringLiteral("let's get"), QStringLiteral("begin")}},
        // Heading/prompt text, not the "Target Disk: vda" row on the summary.
        // "destination" was added upstream after measuring the frontends'
        // real headings: Niri's is the single word "Destination", so it read
        // as "no disk screen" for a frontend that plainly has one.
        // The two product-name variants ("where tunaos will/should be
        // installed") collapsed upstream into the name-free "be installed",
        // which matches both and also matches "where Skipjack will be
        // installed" — the substituted wording this frontend now renders.
        {QStringLiteral("disk"), true,
         {QStringLiteral("select target disk"), QStringLiteral("select a disk"),
          QStringLiteral("choose the disk"), QStringLiteral("available disks"),
          QStringLiteral("be installed"), QStringLiteral("destination")}},
        // NOT bare "encrypt": that matches the summary page's "Encryption: None"
        // field label, which is the OPPOSITE of having reached an encryption
        // screen — it is the exact false positive that once reported an
        // encryption screen this frontend did not have at all.
        {QStringLiteral("encryption"), false,
         {QStringLiteral("disk encryption"), QStringLiteral("encrypt this disk"),
          QStringLiteral("enter passphrase"), QStringLiteral("luks passphrase"),
          QStringLiteral("encryption passphrase")}},
        {QStringLiteral("summary"), true,
         {QStringLiteral("confirm installation"),
          QStringLiteral("review your choices"), QStringLiteral("summary"),
          QStringLiteral("ready to install"), QStringLiteral("about to install")}},
        // NOT "%" and NOT bare "install": one character matches OCR noise, and
        // the disk page reads "... will be installed". Progress screens
        // say what they are DOING, so match that instead.
        //
        // NOT bare "installing" either — Niri's encryption page says "without
        // reinstalling", and "installing" is a substring of it. The trailing
        // entries were added upstream after zero of four frontends matched the
        // original list; "partitioning" and "installing image" are fisherman's
        // own step lines, so they appear on every frontend's progress screen
        // and on no other screen.
        //
        // "installing tunaos" was dropped upstream with the other product-name
        // keywords; the progress line now reads "Installing Skipjack onto
        // /dev/…". Nothing is lost here — fisherman's own "partitioning" and
        // "installing image" step lines already credit this screen.
        {QStringLiteral("install"), false,
         {QStringLiteral("installation progress"), QStringLiteral("copying files"),
          QStringLiteral("deploying"), QStringLiteral("please wait"),
          QStringLiteral("writing image"), QStringLiteral("installing\u2026"),
          QStringLiteral("partitioning"), QStringLiteral("installing image")}},
        // NOT "reboot"/"restart", NOT bare "complete"/"finished"/"success":
        // a LOGIN GREETER satisfies those. cosmic-greeter's power menu offers
        // Restart, Power Off and Suspend, so tunaOS run 31183217981 — stuck on
        // the greeter with the installer never launched — was still credited
        // with reaching the FINISHED screen. Synced from tuna-os/tunaOS#1075.
        {QStringLiteral("done"), false,
         {QStringLiteral("installation complete"),
          QStringLiteral("installation finished"),
          QStringLiteral("is installed"),
          QStringLiteral("has been installed"),
          QStringLiteral("remove the installation media"),
          QStringLiteral("restart to boot"),
          QStringLiteral("reboot into")}},
    };
}

// Every string the page put in its widget tree — what the keywords are matched
// against. Scoped to the page the stack is currently showing: walking the whole
// wizard would collect all six pages' text at once and credit every screen on
// every frame, which is precisely the false-parity failure the spec's comments
// warn about. isVisibleTo() prunes the sub-widgets a page hides from itself
// (the passphrase fields when encryption is off), and works regardless of
// whether the offscreen top-level counts as shown.
inline QString pageText(QWidget *page)
{
    if (!page)
        return QString();
    QStringList parts;
    const auto add = [&parts](const QString &s) {
        if (!s.trimmed().isEmpty())
            parts << s;
    };
    add(page->windowTitle());
    const auto widgets = page->findChildren<QWidget *>();
    for (QWidget *w : widgets) {
        if (!w->isVisibleTo(page))
            continue;
        if (auto *l = qobject_cast<QLabel *>(w))
            add(l->text());
        else if (auto *b = qobject_cast<QAbstractButton *>(w))
            add(b->text());
        else if (auto *g = qobject_cast<QGroupBox *>(w))
            add(g->title());
        else if (auto *p = qobject_cast<QPlainTextEdit *>(w))
            add(p->toPlainText());
        else if (auto *t = qobject_cast<QTextEdit *>(w))
            add(t->toPlainText());
    }
    return parts.join(QLatin1Char(' '));
}

// Grayscale stddev, normalised 0..1 — the same "is the screen blank" measure
// the VM walkthrough takes with ImageMagick.
inline double stddev(const QImage &img)
{
    double sum = 0, sq = 0;
    int n = 0;
    for (int y = 0; y < img.height(); y += 3) {
        for (int x = 0; x < img.width(); x += 3) {
            const QRgb c = img.pixel(x, y);
            const double luma = (30.0 * qRed(c) + 59.0 * qGreen(c) + 11.0 * qBlue(c)) / 100.0;
            sum += luma;
            sq += luma * luma;
            ++n;
        }
    }
    if (!n)
        return 0.0;
    const double mean = sum / n;
    const double var = qMax(sq / n - mean * mean, 0.0);
    return std::sqrt(var) / 255.0;
}

// Pixels differing between two frames. The VM harness uses ImageMagick's
// absolute-error metric at 5% fuzz; 5% of 255 is ~13, so the same tolerance is
// applied per channel here and the counts stay comparable.
inline int changedPixels(const QImage &a, const QImage &b)
{
    if (a.size() != b.size())
        return a.width() * a.height();
    int changed = 0;
    for (int y = 0; y < a.height(); ++y) {
        for (int x = 0; x < a.width(); ++x) {
            const QRgb p = a.pixel(x, y), q = b.pixel(x, y);
            if (qAbs(qRed(p) - qRed(q)) > 13 || qAbs(qGreen(p) - qGreen(q)) > 13
                || qAbs(qBlue(p) - qBlue(q)) > 13)
                ++changed;
        }
    }
    return changed;
}

struct Page {
    QString name;
    QString png;
    QString text;
    bool rendered = false;
    int colours = 0;
    double flat = 0.0;
    double ink = 0.0;
    double stddev = 0.0;
};

// Writes <outDir>/walkthrough-<flavor>.json and prints a short summary.
inline bool write(const QString &outDir, const QString &flavor,
                  const QVector<Page> &pages, const QString &harness,
                  const QVector<int> &transitions, QTextStream &out)
{
    const auto screens = spec();

    // The crediting rule is lifted from the VM harness and matters as much
    // here: a screen other than the first may only be credited on a page the
    // wizard actually advanced to. A welcome page that describes the whole flow
    // otherwise manufactures rows for screens nobody has seen — run
    // 29675493401 recorded three that way.
    QJsonObject reached, detail;
    for (int i = 0; i < screens.size(); ++i) {
        const Screen &sc = screens[i];
        QJsonArray onPages, hitKeywords;
        QSet<QString> seen;
        for (int p = 0; p < pages.size(); ++p) {
            if (i > 0 && p == 0)
                continue;
            const QString text = pages[p].text.toLower();
            bool hit = false;
            for (const QString &k : sc.keywords) {
                if (text.contains(k)) {
                    hit = true;
                    if (!seen.contains(k)) {
                        seen.insert(k);
                        hitKeywords.append(k);
                    }
                }
            }
            if (hit)
                onPages.append(pages[p].name);
        }
        const bool ok = !onPages.isEmpty();
        reached[sc.id] = ok;
        QJsonObject d;
        d[QStringLiteral("required")] = sc.required;
        d[QStringLiteral("reached")] = ok;
        d[QStringLiteral("on_pages")] = onPages;
        d[QStringLiteral("matched_keywords")] = hitKeywords;
        detail[sc.id] = d;
    }

    int renderedFrames = 0;
    QJsonArray pageArr;
    for (const Page &p : pages) {
        if (p.rendered)
            ++renderedFrames;
        QJsonObject o;
        o[QStringLiteral("name")] = p.name;
        o[QStringLiteral("png")] = p.png;
        o[QStringLiteral("rendered")] = p.rendered;
        o[QStringLiteral("colours")] = p.colours;
        o[QStringLiteral("flat")] = p.flat;
        o[QStringLiteral("ink")] = p.ink;
        o[QStringLiteral("stddev")] = p.stddev;
        pageArr.append(o);
    }

    int advanced = 0, states = 1;
    QJsonArray transArr;
    for (int t : transitions) {
        transArr.append(t);
        if (t > kDiffPixels) {
            ++advanced;
            ++states;
        }
    }

    QJsonObject summary;
    // ── the fields tuna-os/tunaOS's parity matrix reads ──────────────────
    summary[QStringLiteral("flavor")] = flavor;
    summary[QStringLiteral("frames")] = pages.size();
    summary[QStringLiteral("rendered_frames")] = renderedFrames;
    summary[QStringLiteral("advanced_transitions")] = advanced;
    summary[QStringLiteral("visual_states")] = pages.isEmpty() ? 0 : states;
    // Null, not "ret": pages are driven programmatically, so claiming a key
    // worked when none was pressed would be exactly the self-satisfying
    // assertion docs/INSTALLER-FRONTENDS.md warns about.
    summary[QStringLiteral("activation_key")] = QJsonValue();
    summary[QStringLiteral("ocr")] = false; // item tree, not OCR
    summary[QStringLiteral("screens")] = reached;
    summary[QStringLiteral("strict")] = true;
    summary[QStringLiteral("failures")] = 0;
    // ── extra context; a consumer reading only the above is unaffected ────
    summary[QStringLiteral("source")] = QStringLiteral("offscreen-capture");
    summary[QStringLiteral("harness")] = harness;
    // The KDE capture reads a QML item tree (tests/capture.cpp itemText()), not
    // a QWidget one. Same kind of evidence, and the field has to say which.
    summary[QStringLiteral("text_source")] = QStringLiteral("qml-item-tree");
    summary[QStringLiteral("screens_detail")] = detail;
    summary[QStringLiteral("pages")] = pageArr;
    summary[QStringLiteral("transition_pixels")] = transArr;
    summary[QStringLiteral("notes")] = QStringLiteral(
        "GPU-less capture: pages are driven programmatically and text is read "
        "from the item tree, so this reports SCREEN PARITY only. It does not "
        "measure keyboard navigation, compositor rendering, or that the "
        "frontend launches under its real desktop — those stay the VM "
        "walkthrough's job.");

    const QString path = outDir + QStringLiteral("/walkthrough-") + flavor
        + QStringLiteral(".json");
    QFile f(path);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Text)) {
        out << "FAIL: could not write " << path << "\n";
        return false;
    }
    f.write(QJsonDocument(summary).toJson(QJsonDocument::Indented));
    f.close();

    out << "\n  parity report -> walkthrough-" << flavor << ".json\n";
    QStringList missing;
    for (const Screen &sc : screens) {
        const bool ok = reached[sc.id].toBool();
        QStringList where;
        for (const auto v : detail[sc.id].toObject()[QStringLiteral("on_pages")].toArray())
            where << v.toString();
        out << QStringLiteral("    %1 %2 (%3) %4\n")
                   .arg(sc.id, -11)
                   .arg(ok ? QStringLiteral("reached") : QStringLiteral("NOT reached"), -12)
                   .arg(sc.required ? QStringLiteral("required") : QStringLiteral("optional"), -8)
                   .arg(where.isEmpty() ? QStringLiteral("-") : where.join(QStringLiteral(", ")));
        if (sc.required && !ok)
            missing << sc.id;
    }
    // Reported, not fatal. This capture's job is to FILL the parity matrix;
    // deciding what a gap costs is the matrix's job, and failing the screenshot
    // build over it would just get the emitter switched off.
    if (!missing.isEmpty())
        out << "    NOTE: required screen(s) not detected: "
            << missing.join(QStringLiteral(", ")) << "\n";
    out.flush();
    return true;
}

} // namespace parity
