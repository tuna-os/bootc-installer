// A thin asynchronous Varlink client for Qt 6: JSON over a QLocalSocket.
//
// A message is one JSON object followed by a NUL byte. One call is in
// flight at a time; a second call waits in a queue. There is no Q_OBJECT
// in this class, so a build needs no moc step.
//
// Passphrases and recovery keys pass through `parameters`. This header
// never logs them.
#pragma once

#include <QByteArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocalSocket>
#include <QQueue>
#include <functional>

namespace tuna {

class VarlinkClient
{
public:
    struct Reply {
        QJsonObject parameters;
        bool continues = false; // true: more replies follow
        QString error; // non-empty: an error reply, the call is over
        bool transportFailed = false; // the socket failed or the peer sent junk
    };
    using Handler = std::function<void(const Reply &)>;

    explicit VarlinkClient(const QString &path)
    {
        m_socket.connectToServer(path);
        QObject::connect(&m_socket, &QLocalSocket::readyRead, &m_socket, [this] { onReadyRead(); });
        QObject::connect(&m_socket, &QLocalSocket::disconnected, &m_socket, [this] { failAll(); });
    }

    // `handler` runs once per reply. For a call with `more`, it runs until a
    // reply has continues == false, or an error.
    void call(const QString &method, const QJsonObject &parameters, bool more, Handler handler)
    {
        QJsonObject request{{"method", method}, {"parameters", parameters}};
        if (more) {
            request.insert("more", true);
        }
        m_pending.enqueue({QJsonDocument(request).toJson(QJsonDocument::Compact) + '\0', std::move(handler)});
        if (m_pending.size() == 1) {
            send();
        }
    }

private:
    struct Pending {
        QByteArray wire;
        Handler handler;
    };

    void send() { m_socket.write(m_pending.head().wire); }

    void onReadyRead()
    {
        m_buffer += m_socket.readAll();
        for (int end; (end = m_buffer.indexOf('\0')) >= 0 && !m_pending.isEmpty();) {
            const QByteArray raw = m_buffer.left(end);
            m_buffer.remove(0, end + 1);
            const QJsonDocument doc = QJsonDocument::fromJson(raw);
            Reply reply;
            if (!doc.isObject()) {
                reply.transportFailed = true;
            } else {
                const QJsonObject o = doc.object();
                reply.parameters = o.value("parameters").toObject();
                reply.continues = o.value("continues").toBool();
                reply.error = o.value("error").toString();
            }
            const bool last = reply.transportFailed || !reply.error.isEmpty() || !reply.continues;
            Handler handler = m_pending.head().handler;
            if (last) {
                m_pending.dequeue();
            }
            handler(reply);
            if (last && !m_pending.isEmpty()) {
                send();
            }
        }
    }

    void failAll()
    {
        while (!m_pending.isEmpty()) {
            Reply reply;
            reply.transportFailed = true;
            Handler handler = m_pending.dequeue().handler;
            handler(reply);
        }
    }

    QLocalSocket m_socket;
    QByteArray m_buffer;
    QQueue<Pending> m_pending;
};

} // namespace tuna
