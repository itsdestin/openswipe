// SPDX-FileCopyrightText: 2026 Destin Moss <https://youcoded.ai>
//
// SPDX-License-Identifier: MIT

// Read-only ownership probe: no GUI, D-Bus, configuration writes or environment overrides.
#include <KConfig>
#include <KConfigGroup>
#include <QCoreApplication>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QList>
#include <QStandardPaths>
#include <QRegularExpression>
#include <cstdio>

static QJsonValue entry(const KConfigGroup &group, const char *key)
{
    return group.hasKey(key) ? QJsonValue(group.readEntry(key, QString())) : QJsonValue(QJsonValue::Null);
}

static bool plainAfterExpansion(const QByteArray &value)
{
    // WHY (issue #27): KDE's own Virtual Keyboard settings page stores its choice as a
    // "path" entry, InputMethod[$e]=..., and writes a home folder as $HOME. Refusing every
    // [$e] blocked anyone who had ever picked a keyboard there. KConfig expands only '$'
    // sequences, so a value is safe to restore as a plain string when it holds no '$' at
    // all, "$$" (KConfig's escaped literal '$'), or a leading $HOME — exactly what
    // KConfigGroup::writePathEntry produces. $HOME is the same for this probe and KWin
    // (same user); any other variable could differ between them, so it is refused.
    for (qsizetype i = 0; i < value.size(); ++i) {
        if (value.at(i) != '$')
            continue;
        if (i + 1 < value.size() && value.at(i + 1) == '$') {
            ++i;
            continue;
        }
        if (i == 0 && value.startsWith("$HOME") && (value.size() == 5 || value.at(5) == '/')) {
            i += 4;
            continue;
        }
        return false;
    }
    return true;
}

static bool supportedUserSyntax(const QByteArray &bytes)
{
    // WHY a deliberately narrow whitelist, not a replacement KConfig parser:
    // public KConfig value APIs discard deletion, expansion and locale provenance.
    // Schema 2 can restore only plain values/absence (plus [$e] values whose expansion
    // is provably the same string for this user, see plainAfterExpansion). Unrelated
    // groups do not affect those values. KConfig remains authoritative for values,
    // precedence and immutable flags.
    const QRegularExpression key(QStringLiteral(R"(^[A-Za-z0-9_ .:/-]+(\[\$i\]|\[\$e\])?$)"));
    bool wayland = false;
    for (const auto &rawLine : bytes.split('\n')) {
        const auto line = rawLine.trimmed();
        if (line.isEmpty() || line.startsWith('#'))
            continue;
        if (line.startsWith('[')) {
            // WHY parse headers the way KConfig does (kconfigini.cpp) instead of whitelisting
            // characters (issue #27): any odd header elsewhere in kwinrc, such as the
            // [$Version] group older KDE upgrades leave behind, used to block setup. Only a
            // header that KConfig reads as the [Wayland] root group can change our values.
            // KConfig joins "[a][b]" segments while ']' is followed by '[' and silently
            // ignores anything else after a ']', so "[Wayland]junk" would still be Wayland:
            // require the segments to cover the whole line. Backslash escapes are decoded
            // in names and could spell Wayland, so those headers are still refused.
            if (line.contains('\\'))
                return false;
            QList<QByteArray> segments;
            qsizetype start = 1;
            for (;;) {
                const auto end = line.indexOf(']', start);
                if (end < 0)
                    return false;
                segments.append(line.mid(start, end - start));
                if (end + 1 == line.size())
                    break;
                if (line.at(end + 1) != '[')
                    return false;
                start = end + 2;
            }
            if (segments.size() > 1 && segments.last() == "$i")
                segments.removeLast(); // an immutability flag, not a name; KConfig reports locks
            if (segments == QList<QByteArray>{"$i"})
                continue; // file-wide immutability flag: the current group is unchanged
            // WHY refuse other flag-shaped segments such as [$d]: today's KConfig reads them as
            // plain names, but they look like option flags and another KConfig version could
            // treat them as one. [$Version] (capital, a real group name) is not flag-shaped.
            static const QRegularExpression flag(QStringLiteral(R"(^\$[a-z]+$)"));
            for (const auto &segment : segments) {
                if (flag.match(QString::fromLatin1(segment)).hasMatch())
                    return false;
            }
            // WHY require a named root: KConfig keeps empty child groups ([Wayland][]) distinct.
            wayland = segments == QList<QByteArray>{"Wayland"};
            continue;
        }
        if (!wayland)
            continue; // unrelated entries remain opaque and are never restored by setup
        // Reject non-ASCII identifiers and control bytes rather than guessing
        // whether KConfig will normalize them into a different key.
        const auto separator = line.indexOf('=');
        if (separator < 0)
            return false;
        const auto identifier = line.left(separator).trimmed();
        for (const auto character : identifier) {
            if (character < 32 || character > 126)
                return false;
        }
        if (!key.match(QString::fromLatin1(identifier)).hasMatch())
            return false;
        if (identifier.endsWith("[$e]") && !plainAfterExpansion(line.mid(separator + 1).trimmed()))
            return false;
    }
    return true;
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    // WHY fail closed: KConfig can treat an unreadable source as empty. Absence is
    // trustworthy only if every existing participating source can actually be read.
    for (const auto &directory : QStandardPaths::standardLocations(QStandardPaths::GenericConfigLocation)) {
        for (const char *name : {"kwinrc", "kdeglobals"}) {
            QFileInfo info(directory + QLatin1Char('/') + QString::fromLatin1(name));
            if (info.exists() || info.isSymbolicLink()) {
                QFile file(info.filePath());
                if (!info.isFile() || !file.open(QIODevice::ReadOnly)) {
                    std::fputs("Cannot read a KConfig source; ownership cannot be established.\n", stderr);
                    return 2;
                }
                if (directory == QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation)
                    && QByteArray(name) == "kwinrc" && !supportedUserSyntax(file.readAll())) {
                    std::fputs("Unsupported user KConfig syntax: setup cannot preserve deletion, expansion, "
                               "localized or other non-plain entries. No ownership snapshot is available.\n", stderr);
                    return 2;
                }
            }
        }
    }
    // WHY two native views: an absolute SimpleConfig excludes inherited session defaults;
    // the full relative view follows KWin's KSharedConfig defaults, including Kiosk locks.
    // Checking BOTH prevents an effective immutable overlay from hiding raw user locks.
    KConfig raw(QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation)
                    + QStringLiteral("/kwinrc"), KConfig::SimpleConfig);
    KConfig effective(QStringLiteral("kwinrc"), KConfig::FullConfig);
    const KConfigGroup user(&raw, "Wayland");
    const KConfigGroup merged(&effective, "Wayland");
    QJsonObject result;
    for (const char *key : {"InputMethod", "VirtualKeyboardMode"}) {
        result.insert(QString::fromLatin1(key), QJsonObject{
            {QStringLiteral("raw"), entry(user, key)},
            {QStringLiteral("effective"), entry(merged, key)},
            {QStringLiteral("immutable"), user.isEntryImmutable(key) || merged.isEntryImmutable(key)}});
    }
    const auto json = QJsonDocument(result).toJson(QJsonDocument::Compact);
    return std::fwrite(json.constData(), 1, json.size(), stdout) == size_t(json.size()) ? 0 : 1;
}
