// Tests for the Qt recipe. Build and run: see shared/client/README.md.
// The peer is a QLocalServer test double for the wire format, not the mock daemon.
#include "sizes.h"
#include "varlinkclient.h"

#include <QCoreApplication>
#include <QFile>
#include <QJsonArray>
#include <QLocalServer>
#include <QTemporaryDir>
#include <QTimer>
#include <cstdio>

static int failures = 0;
#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            std::fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #cond);                    \
            ++failures;                                                                            \
        }                                                                                          \
    } while (0)

static void testSizes(const QString &fixturePath)
{
    QFile f(fixturePath);
    CHECK(f.open(QIODevice::ReadOnly));
    const QJsonArray cases = QJsonDocument::fromJson(f.readAll()).object().value("cases").toArray();
    CHECK(cases.size() > 10);
    for (const QJsonValue &v : cases) {
        const QJsonObject c = v.toObject();
        const QString input = c.value("input").toString();
        const QString name = c.value("name").toString();
        if (tuna::normalizeSizeText(input) != c.value("normalized").toString()) {
            std::fprintf(stderr, "FAIL normalize %s\n", qPrintable(name));
            ++failures;
        }
        const auto bytes = tuna::parseSize(input);
        const QJsonValue want = c.value("bytes");
        const bool same = want.isNull() ? !bytes.has_value()
                                        : (bytes.has_value() && *bytes == qint64(want.toDouble()));
        if (!same) {
            std::fprintf(stderr, "FAIL parse %s\n", qPrintable(name));
            ++failures;
        }
    }
}

// Frames replies in two reads, one error stream, and a queued second call.
static void testWire(QCoreApplication &app)
{
    QTemporaryDir dir;
    const QString path = dir.filePath("s");
    QLocalServer server;
    CHECK(server.listen(path));
    QByteArray received;
    QObject::connect(&server, &QLocalServer::newConnection, [&] {
        QLocalSocket *peer = server.nextPendingConnection();
        QObject::connect(peer, &QLocalSocket::readyRead, [&, peer] {
            received += peer->readAll();
            while (received.contains('\0')) {
                const int end = received.indexOf('\0');
                const QJsonObject req = QJsonDocument::fromJson(received.left(end)).object();
                received.remove(0, end + 1);
                const QString method = req.value("method").toString();
                if (method == "io.systemd.SysInstall.Run") {
                    const QByteArray a = "{\"parameters\":{\"progress\":10},\"continues\":true}";
                    const QByteArray b = "{\"parameters\":{}}";
                    peer->write(a + '\0' + b.left(5));
                    peer->flush();
                    QTimer::singleShot(20, peer, [peer, b] {
                        peer->write(b.mid(5) + '\0');
                    });
                } else {
                    peer->write("{\"error\":\"io.tunaos.Fisherman.DeviceLost\","
                                "\"parameters\":{\"passphrase\":\"x\"}}"
                                + QByteArray(1, '\0'));
                }
            }
        });
    });

    tuna::VarlinkClient client(path);
    int streamed = 0;
    bool streamEnded = false;
    QString error;
    client.call("io.systemd.SysInstall.Run", {{"node", "/dev/vda"}}, true,
                [&](const tuna::VarlinkClient::Reply &r) {
                    ++streamed;
                    streamEnded = !r.continues;
                });
    client.call("io.tunaos.Fisherman.Install", {}, false, [&](const tuna::VarlinkClient::Reply &r) {
        error = r.error;
        app.quit();
    });
    QTimer::singleShot(3000, &app, &QCoreApplication::quit);
    app.exec();

    CHECK(streamed == 2);
    CHECK(streamEnded);
    CHECK(error == "io.tunaos.Fisherman.DeviceLost");
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    testSizes(argc > 1 ? argv[1] : "../fixtures/sizes.json");
    testWire(app);
    std::printf(failures ? "FAILED: %d\n" : "ok\n", failures);
    return failures ? 1 : 0;
}
