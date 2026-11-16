// SPDX-FileCopyrightText: 2026 Destin Moss <https://youcoded.ai>
//
// SPDX-License-Identifier: GPL-2.0-only OR GPL-3.0-only OR LicenseRef-KDE-Accepted-GPL

#include <QtTest>
#include <QTemporaryDir>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QQuickWindow>
#include <QQuickItem>
#include <QScopeGuard>
#include <QElapsedTimer>
#include <QGuiApplication>
#include "languagefixtures.h"
#include <QtVirtualKeyboard/QVirtualKeyboardInputContext>
#include "swipeinputmethod.h"
#include "languagetextrules.h"
class LanguageIntegrationTest : public QObject {
    Q_OBJECT
private slots:
    void packagedPacksNeedNoOverrideOrGate() {
        const auto packs=qEnvironmentVariable("SWIPEKB_TEST_LANGUAGE_PACKS");
        if(packs.isEmpty()) QSKIP("Explicit verified pack fixture required");
        QTemporaryDir root;
        QVERIFY(QDir().mkpath(root.filePath("language-packs")));
        for(const auto &name:QDir(packs).entryList(QDir::Files))
            QVERIFY(QFile::copy(QDir(packs).filePath(name),root.filePath("language-packs/"+name)));
        const auto oldModel=qgetenv("SWIPEKB_MODEL_DATA"), oldPacks=qgetenv("SWIPEKB_LANGUAGE_PACKS");
        const bool hadModel=qEnvironmentVariableIsSet("SWIPEKB_MODEL_DATA"), hadPacks=qEnvironmentVariableIsSet("SWIPEKB_LANGUAGE_PACKS");
        const auto restore=qScopeGuard([&] {
            if(hadModel) qputenv("SWIPEKB_MODEL_DATA",oldModel); else qunsetenv("SWIPEKB_MODEL_DATA");
            if(hadPacks) qputenv("SWIPEKB_LANGUAGE_PACKS",oldPacks); else qunsetenv("SWIPEKB_LANGUAGE_PACKS");
        });
        qputenv("SWIPEKB_MODEL_DATA",root.path().toUtf8()); qunsetenv("SWIPEKB_LANGUAGE_PACKS");
        SwipeInputMethod im;
        for(const auto &locale:{"es-ES","es-MX","fr-FR","de-DE"}) {
            im.setPhysicalLayout(QString(locale).startsWith("fr") ? "azerty" : QString(locale).startsWith("de") ? "qwertz" : "qwerty");
            im.setInputMode(locale,QVirtualKeyboardInputEngine::InputMode::Latin);
            QVERIFY2(im.isReady(),qPrintable(im.profileSnapshot().unavailableReason));
            QVERIFY(im.profileSnapshot().capabilities.nextWord);
            QVERIFY(im.profileSnapshot().assets.contains("contextModel"));
            QVERIFY(im.profileSnapshot().assets.contains("contextVocab"));
            QCOMPARE(im.profileSnapshot().requestedLocale,QString(locale));
        }
    }
    // WHY: a missing language file (e.g. never downloaded, or deleted) must not take the keyboard away. The language
    // still swipes and types; only the next-word/completion suggestions go.
    void missingNextWordFilesKeepTheLanguageUsable() {
        const auto packs=qEnvironmentVariable("SWIPEKB_TEST_LANGUAGE_PACKS");
        if(packs.isEmpty() || !QFileInfo::exists(packs+"/fr.ngram")) QSKIP("Explicit verified pack fixture required");
        QTemporaryDir root;
        QVERIFY(QDir().mkpath(root.filePath("language-packs")));
        for(const auto &name:QDir(packs).entryList(QDir::Files))
            if(name!="fr.ngram" && name!="es.vocab.tsv")
                QVERIFY(QFile::copy(QDir(packs).filePath(name),root.filePath("language-packs/"+name)));
        const auto oldModel=qgetenv("SWIPEKB_MODEL_DATA"), oldPacks=qgetenv("SWIPEKB_LANGUAGE_PACKS");
        const bool hadModel=qEnvironmentVariableIsSet("SWIPEKB_MODEL_DATA"), hadPacks=qEnvironmentVariableIsSet("SWIPEKB_LANGUAGE_PACKS");
        const auto restore=qScopeGuard([&] {
            if(hadModel) qputenv("SWIPEKB_MODEL_DATA",oldModel); else qunsetenv("SWIPEKB_MODEL_DATA");
            if(hadPacks) qputenv("SWIPEKB_LANGUAGE_PACKS",oldPacks); else qunsetenv("SWIPEKB_LANGUAGE_PACKS");
        });
        qputenv("SWIPEKB_MODEL_DATA",root.path().toUtf8()); qunsetenv("SWIPEKB_LANGUAGE_PACKS");
        SwipeInputMethod im;
        for(const auto &locale:{"fr-FR","es-ES"}) {
            im.setPhysicalLayout(QString(locale).startsWith("fr") ? "azerty" : "qwerty");
            im.setInputMode(locale,QVirtualKeyboardInputEngine::InputMode::Latin);
            QVERIFY2(im.isReady(),qPrintable(im.profileSnapshot().unavailableReason));
            QVERIFY(im.profileSnapshot().capabilities.swipe); QVERIFY(!im.profileSnapshot().capabilities.nextWord);
            QVERIFY(!im.profileSnapshot().assets.contains("contextModel"));
            QCOMPARE(im.diagnostics()["predictionStatus"].toString(),QString("context-model-unavailable"));
        }
        im.setPhysicalLayout("qwertz");
        im.setInputMode("de-DE",QVirtualKeyboardInputEngine::InputMode::Latin);
        QVERIFY(im.isReady()); QVERIFY(im.profileSnapshot().capabilities.nextWord); // untouched languages keep theirs
    }
    void incompleteGeometryKeepsTapping() {
        const QString packs=qEnvironmentVariable("SWIPEKB_TEST_LANGUAGE_PACKS");
        if (packs.isEmpty()) QSKIP("Explicit local language pack fixture not supplied");
        qputenv("SWIPEKB_LANGUAGE_PACKS",packs.toUtf8());
        SwipeInputMethod im;
        im.setPhysicalLayout("qwerty");
        im.setInputMode("es_ES",QVirtualKeyboardInputEngine::InputMode::Latin);
        QVERIFY(im.isReady());
        QCOMPARE(im.diagnostics()["engineReady"].toBool(),true);
        QCOMPARE(im.diagnostics()["activeFieldPolicy"].toString(),QString("unknown"));
        QVariantList keys;
        for (char c='a';c<='z';++c) keys.append(QVariantMap{{"letter",QString(QChar(c))},
            {"x",(c-'a')*10},{"y",0},{"w",10},{"h",10}});
        QVERIFY(!im.isReadyForLayout(keys)); // Spanish ñ has no undeclared n fallback.
        keys.append(QVariantMap{{"letter","ñ"},{"x",260},{"y",0},{"w",10},{"h",10}});
        QVERIFY(im.isReadyForLayout(keys));
        QVERIFY(!im.keyEvent(Qt::Key_N,"n",Qt::NoModifier));
        qunsetenv("SWIPEKB_LANGUAGE_PACKS");
    }
    void loadedProfilesClearAlternativesAndRejectHeldGesture() {
        const auto assets=qEnvironmentVariable("SWIPEKB_TEST_ENGLISH_ASSETS"), packs=qEnvironmentVariable("SWIPEKB_TEST_LANGUAGE_PACKS");
        if (assets.isEmpty() || packs.isEmpty()) QSKIP("Explicit pinned English assets and real language packs required");
        QTemporaryDir data;
        const QList<QByteArray> names{"SWIPEKB_MODEL_DATA","SWIPEKB_LANGUAGE_PACKS","SWIPEKB_DATA"};
        QHash<QByteArray,QByteArray> old; QHash<QByteArray,bool> existed;
        for (const auto &name:names) { old[name]=qgetenv(name); existed[name]=qEnvironmentVariableIsSet(name.constData()); }
        const auto restore=qScopeGuard([&] { for(const auto &name:names) { if(existed[name]) qputenv(name,old[name]); else qunsetenv(name); } });
        qputenv("SWIPEKB_MODEL_DATA",assets.toUtf8()); qputenv("SWIPEKB_LANGUAGE_PACKS",packs.toUtf8());
        qputenv("SWIPEKB_DATA",data.path().toUtf8());
        QQmlEngine qml;
        QQmlComponent component(&qml);
        component.setData(R"(
            import QtQuick
            import QtQuick.VirtualKeyboard
            Item {
                width: 1000; height: 400
                property QtObject context: InputContext
                property alias text: editor.text
                function focusEditor() { editor.forceActiveFocus() }
                TextInput { id: editor; width: 900; height: 100; focus: true; inputMethodHints: Qt.ImhNone }
            }
        )",QUrl());
        std::unique_ptr<QObject> root(component.create()); QVERIFY2(root,qPrintable(component.errorString()));
        auto *ic=qobject_cast<QVirtualKeyboardInputContext *>(root->property("context").value<QObject *>()); QVERIFY(ic);
        QQuickWindow window; window.resize(1000,400);
        qobject_cast<QQuickItem *>(root.get())->setParentItem(window.contentItem()); window.show();
        QVERIFY(QMetaObject::invokeMethod(root.get(),"focusEditor")); QTRY_VERIFY(ic->inputItem());
        SwipeInputMethod im;
        ic->inputEngine()->setInputMethod(&im);
        const auto detach=qScopeGuard([&] { ic->inputEngine()->setInputMethod(nullptr); });
        im.setPhysicalLayout("qwerty"); im.setInputMode("en_GB",QVirtualKeyboardInputEngine::InputMode::Latin);
        QVERIFY2(im.isReady(),qPrintable(im.profileSnapshot().unavailableReason));
        auto geometry=[](bool spanish) {
            QVariantList keys; const QStringList rows{"qwertyuiop","asdfghjkl","zxcvbnm"};
            for(int r=0;r<rows.size();++r) for(int i=0;i<rows[r].size();++i)
                keys.append(QVariantMap{{"letter",QString(rows[r][i])},{"x",i*100},{"y",r*100},{"w",100},{"h",100}});
            if(spanish) keys.append(QVariantMap{{"letter","ñ"},{"x",900},{"y",100},{"w",100},{"h",100}});
            return keys;
        };
        auto trace=[](const QString &word,const QVariantList &keys) {
            QVariantList points; QPointF previous;
            for(const auto &letter:word) {
                QVariantMap key;
                for(const auto &entry:keys) if(entry.toMap()["letter"].toString()==QString(letter)) key=entry.toMap();
                const QPointF center(key["x"].toDouble()+50,key["y"].toDouble()+50);
                if(points.isEmpty()) points.append(QVariantMap{{"x",center.x()},{"y",center.y()},{"t",0}});
                else for(int step=1;step<=8;++step) {
                    const auto p=previous+(center-previous)*(step/8.0);
                    points.append(QVariantMap{{"x",p.x()},{"y",p.y()},{"t",points.size()*16}});
                }
                previous=center;
            }
            return points;
        };
        const auto englishKeys=geometry(false), englishTrace=trace("the",englishKeys);
        const int token=im.beginSwipe(); QVERIFY(token>=0); im.finishSwipe(englishTrace,englishKeys,token);
        QTRY_VERIFY(!root->property("text").toString().isEmpty());
        QVERIFY(im.selectionListItemCount(QVirtualKeyboardSelectionListModel::Type::WordCandidateList)>0);
        const auto committed=root->property("text").toString();
        const auto epoch=im.profileSnapshot().epoch; const int held=im.beginSwipe(); QVERIFY(held>=0);
        im.setInputMode("es_ES",QVirtualKeyboardInputEngine::InputMode::Latin);
        QVERIFY2(im.isReady(),qPrintable(im.profileSnapshot().unavailableReason));
        QVERIFY(im.profileSnapshot().epoch>epoch); QCOMPARE(im.profileSnapshot().requestedLocale,QString("es-ES"));
        QVERIFY(im.profileSnapshot().capabilities.nextWord);
        QCOMPARE(im.selectionListItemCount(QVirtualKeyboardSelectionListModel::Type::WordCandidateList),0);
        im.finishSwipe(englishTrace,englishKeys,held); QCOMPARE(root->property("text").toString(),committed);
        const auto spanishKeys=geometry(true); const int spanishToken=im.beginSwipe(); QVERIFY(spanishToken>=0);
        im.finishSwipe(trace("casa",spanishKeys),spanishKeys,spanishToken);
        QTRY_VERIFY(root->property("text").toString().size()>committed.size());
        QVERIFY(im.selectionListItemCount(QVirtualKeyboardSelectionListModel::Type::WordCandidateList)>0);
        const auto spanishCommitted=root->property("text").toString(); const int abandoned=im.beginSwipe();
        im.setPhysicalLayout("unknown"); QVERIFY(!im.isReady());
        QCOMPARE(im.selectionListItemCount(QVirtualKeyboardSelectionListModel::Type::WordCandidateList),0);
        im.finishSwipe(trace("casa",spanishKeys),spanishKeys,abandoned);
        QCOMPARE(root->property("text").toString(),spanishCommitted);
        QVERIFY(!QFileInfo::exists(data.filePath("swipes.jsonl")));
    }
    // WHY (issue #24): "?123" switches the input mode away from Latin and back; rotation passes through the same path.
    // Coming back must take the same engine back (no dictionary reload), while the detour itself exposes no engine.
    void symbolsDetourReusesTheEngineAndNothingElseDoes() {
        const auto assets=qEnvironmentVariable("SWIPEKB_TEST_ENGLISH_ASSETS"), packs=qEnvironmentVariable("SWIPEKB_TEST_LANGUAGE_PACKS");
        if (assets.isEmpty() || packs.isEmpty()) QSKIP("Explicit pinned English assets and real language packs required");
        QTemporaryDir data;
        const QList<QByteArray> names{"SWIPEKB_MODEL_DATA","SWIPEKB_LANGUAGE_PACKS","SWIPEKB_DATA"};
        QHash<QByteArray,QByteArray> old; QHash<QByteArray,bool> existed;
        for (const auto &name:names) { old[name]=qgetenv(name); existed[name]=qEnvironmentVariableIsSet(name.constData()); }
        const auto restore=qScopeGuard([&] { for(const auto &name:names) { if(existed[name]) qputenv(name,old[name]); else qunsetenv(name); } });
        qputenv("SWIPEKB_MODEL_DATA",assets.toUtf8()); qputenv("SWIPEKB_LANGUAGE_PACKS",packs.toUtf8());
        qputenv("SWIPEKB_DATA",data.path().toUtf8());
        SwipeInputMethod im;
        im.setPhysicalLayout("qwerty");
        QElapsedTimer timer; timer.start();
        im.setInputMode("en_US",QVirtualKeyboardInputEngine::InputMode::Latin);
        const auto firstLoad=timer.elapsed();
        QVERIFY2(im.isReady(),qPrintable(im.profileSnapshot().unavailableReason));
        const auto english=im.languageEngine(); QVERIFY(english);
        im.setInputMode("en_US",QVirtualKeyboardInputEngine::InputMode::Numeric);
        QVERIFY(!im.isReady()); QVERIFY(!im.languageEngine());   // nothing may use English's engine in the detour
        timer.restart();
        im.setInputMode("en_US",QVirtualKeyboardInputEngine::InputMode::Latin);
        const auto comeBack=timer.elapsed();
        QVERIFY(im.isReady()); QCOMPARE(im.languageEngine().get(),english.get());
        qInfo("first load %lld ms, return from the symbols page %lld ms",qint64(firstLoad),qint64(comeBack));
        // An unsupported language in between is a detour too.
        im.setInputMode("ja_JP",QVirtualKeyboardInputEngine::InputMode::Latin); QVERIFY(!im.languageEngine());
        im.setInputMode("en_US",QVirtualKeyboardInputEngine::InputMode::Latin); QCOMPARE(im.languageEngine().get(),english.get());
        // An unknown layout is a detour; another supported layout is another profile and gets its own engine.
        im.setPhysicalLayout("unknown"); QVERIFY(!im.languageEngine());
        im.setPhysicalLayout("qwerty"); QCOMPARE(im.languageEngine().get(),english.get());
        im.setPhysicalLayout("azerty"); QVERIFY(im.isReady()); QVERIFY(im.languageEngine().get()!=english.get());
        im.setPhysicalLayout("qwerty"); QVERIFY(im.isReady()); QVERIFY(im.languageEngine().get()!=english.get());
        // Another swipe language, then back: never the old engine (its parked copy is dropped before Spanish is built).
        const auto qwerty=im.languageEngine();
        im.setInputMode("es_ES",QVirtualKeyboardInputEngine::InputMode::Latin);
        QVERIFY(im.isReady()); QVERIFY(im.languageEngine().get()!=qwerty.get());
        im.setInputMode("en_US",QVirtualKeyboardInputEngine::InputMode::Latin);
        QVERIFY(im.isReady()); QVERIFY(im.languageEngine().get()!=qwerty.get());
        // Forgetting what was learned during a detour: the parked engine still holds those words, so it is not reused.
        const auto beforeForget=im.languageEngine();
        im.setInputMode("en_US",QVirtualKeyboardInputEngine::InputMode::Numeric);
        im.forgetEverythingLearned();
        im.setInputMode("en_US",QVirtualKeyboardInputEngine::InputMode::Latin);
        QVERIFY(im.isReady()); QVERIFY(im.languageEngine().get()!=beforeForget.get());
    }
    // WHY (issue #24): checksums are remembered, but a file changed after its first check must still be refused, even
    // when its size and modification time are put back exactly.
    void rememberedChecksumsNeverHideAChangedFile() {
        const auto packs=qEnvironmentVariable("SWIPEKB_TEST_LANGUAGE_PACKS");
        if (packs.isEmpty() || !QFileInfo::exists(packs+"/es.json")) QSKIP("Explicit verified pack fixture required");
        QTemporaryDir root;
        for (const auto &name:QDir(packs).entryList(QDir::Files))
            QVERIFY(QFile::copy(QDir(packs).filePath(name),root.filePath(name)));
        QVERIFY(swipekb::resolveProfile("es-ES","qwerty","Latin",root.path()).capabilities.swipe);
        QVERIFY(swipekb::resolveProfile("es-ES","qwerty","Latin",root.path()).capabilities.swipe);   // remembered
        QFile dictionary(root.filePath("es.combined"));
        const auto modified=QFileInfo(dictionary).lastModified();
        QVERIFY(dictionary.open(QIODevice::ReadWrite));
        QVERIFY(dictionary.seek(dictionary.size()/2)); char byte=0; QVERIFY(dictionary.getChar(&byte));
        QVERIFY(dictionary.seek(dictionary.size()/2)); QVERIFY(dictionary.putChar(char(byte^0x20)));
        QVERIFY(dictionary.flush());   // WHY: the byte must reach the file before its time is put back
        QVERIFY(dictionary.setFileTime(modified,QFileDevice::FileModificationTime));
        dictionary.close();
        QCOMPARE(QFileInfo(dictionary).lastModified(),modified);
        const auto changed=swipekb::resolveProfile("es-ES","qwerty","Latin",root.path());
        QVERIFY(!changed.capabilities.swipe); QVERIFY(changed.unavailableReason.contains("checksum"));
    }
    void switchesRevokeAuthority() {
        QTemporaryDir root;
        qputenv("SWIPEKB_MODEL_DATA",root.path().toUtf8());
        SwipeInputMethod im;
        QSignalSpy invalidated(&im,&SwipeInputMethod::gestureInvalidated);
        QSignalSpy changed(&im,&SwipeInputMethod::profileChanged);
        im.setPhysicalLayout("azerty");
        im.setInputMode("fr_FR",QVirtualKeyboardInputEngine::InputMode::Latin);
        auto fr=im.profileSnapshot();
        QCOMPARE(fr.layoutId,QString("azerty")); QCOMPARE(fr.requestedLocale,QString("fr-FR"));
        QVERIFY(!im.isReady()); QVERIFY(fr.assets.isEmpty());
        QVERIFY(fr.unavailableReason.contains("manifest"));
        const auto count=invalidated.size();
        im.setInputMode("en_GB",QVirtualKeyboardInputEngine::InputMode::Latin);
        auto en=im.profileSnapshot();
        QVERIFY(en.epoch>fr.epoch); QCOMPARE(en.layoutId,QString("azerty"));
        QVERIFY(invalidated.size()>count); QVERIFY(changed.size()>=4);
        QCOMPARE(im.selectionListItemCount(QVirtualKeyboardSelectionListModel::Type::WordCandidateList),0);
        QVERIFY(!im.keyEvent(Qt::Key_A,"a",Qt::NoModifier));
        im.setPhysicalLayout("qwertz"); QVERIFY(im.profileSnapshot().epoch>en.epoch);
        QVERIFY(!im.isReady());
    }
};
int main(int argc,char **argv) {
    QGuiApplication app(argc,argv); LanguageIntegrationTest test;
    const int result=QTest::qExec(&test,argc,argv);
    return result ? result : (languagefixtures::runtimeAvailable() ? 0 : 77);
}
#include "tst_languageintegration.moc"
