# Tabletzeit-Konto-System

## Vision

Jedes Kind bekommt ein **virtuelles Zeitkonto** in Home Assistant.  
Eltern füllen das Konto auf, wenn die Kinder etwas Positives geleistet haben (Lesen, Lernen, Helfen, etc.).  
Das Kind sieht sein Guthaben und kann sich selbst Tabletzeit buchen – direkt vom Tablet aus, über eine kleine App.  
Die gebuchte Zeit wird automatisch als tages-Override in Google Family Link eingetragen, sodass das Gerät entsprechend länger nutzbar ist.

---

## Systemübersicht

```
┌─────────────────────────────────────────────────────────────────┐
│                        Home Assistant                           │
│                                                                 │
│  ┌──────────────────┐   ┌──────────────────┐                   │
│  │  Zeitkonto       │   │  FamilyLink       │                   │
│  │  (input_number)  │──▶│  Integration      │──▶ Google API    │
│  │  Ronja: 120 min  │   │  TodayLimitNumber │    timeLimitOver │
│  │  Emilio: 45 min  │   │  (Gerät pro Kind) │    rides:batchCr │
│  └──────────────────┘   └──────────────────┘                   │
│           ▲                                                     │
│           │ REST API / HA-Service                               │
│           │                                                     │
│  ┌──────────────────┐   ┌──────────────────┐                   │
│  │  Buchungs-       │   │  Eltern-          │                   │
│  │  Service         │   │  Dashboard        │                   │
│  │  (Script/Auto.)  │   │  (Lovelace)       │                   │
│  └──────────────────┘   └──────────────────┘                   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    REST + WebSocket API
                    (kind-spezifischer Token)
                               │
              ┌────────────────┴────────────────┐
              │                                 │
   ┌──────────▼──────────┐           ┌──────────▼──────────┐
   │   Ronja's Tablet    │           │   Emilio's Tablet   │
   │                     │           │                     │
   │  ┌───────────────┐  │           │  ┌───────────────┐  │
   │  │  Android App  │  │           │  │  Android App  │  │
   │  │  (Flutter)    │  │           │  │  (Flutter)    │  │
   │  └───────────────┘  │           │  └───────────────┘  │
   └─────────────────────┘           └─────────────────────┘
```

---

## Komponenten im Detail

### 1. Zeitkonto (HA-Seite)

Jedes Kind erhält eine `input_number`-Entität als Guthaben-Speicher:

| Entität | Kind | Einheit | Min | Max |
|---|---|---|---|---|
| `input_number.zeitkonto_ronja` | Ronja | Minuten | 0 | 600 |
| `input_number.zeitkonto_emilio` | Emilio | Minuten | 0 | 600 |
| `input_number.zeitkonto_lennard` | Lennard | Minuten | 0 | 600 |

**Alternativer Ansatz:** Eigene `sensor`-Entitäten in der FamilyLink-Integration (persistiert über `storage`-Helfer), um alles in einem Paket zu halten. Vorteil: HACS-Installation liefert alles. Nachteil: mehr Komplexität.  
→ **Empfehlung Phase 1:** `input_number` via `configuration.yaml` oder Helpers UI (kein Code nötig, sofort nutzbar).

---

### 2. Buchungs-Service (HA-Seite)

Ein HA-Script (oder Custom Action) führt die Buchungslogik aus:

```
Buchung(kind_id, device_id, betrag_minuten)
  1. Lese aktuelles Guthaben = input_number.zeitkonto_{kind}
  2. Prüfe: Guthaben >= betrag?  →  sonst: Fehler "Kein Guthaben"
  3. Lese aktuelles Tageslimit vom Gerät (TodayLimitNumber)
  4. Neues Tageslimit = aktuelles Limit + betrag
  5. Rufe familylink.set_today_limit(child_id, device_id, neues_limit)
  6. Ziehe betrag vom Guthaben ab: input_number -= betrag
  7. Schreibe Buchungs-Log (optional: logbook / notify)
```

**Sicherheitsregel:** Das HA-Script stellt sicher, dass **nur abgebucht** wird, was der Anruf-Token des Kindes darf. Der Token des Kindes darf nur diesen einen Script-Service aufrufen (kein Schreiben auf `input_number` direkt).

---

### 3. Tablet-App

#### Technologie-Entscheidung: Flutter (Android)

**Flutter** wird als App-Framework gewählt.

| Kriterium | Begründung |
|---|---|
| Kein Web-Hosting nötig | App läuft nativ auf dem Tablet, kein HA-Static-Files-Trick |
| Einfache Installation | APK einmalig seitlich laden (kein Play Store nötig) oder per ADB |
| Selbstkonfigurierend | Setup-Wizard konfiguriert alles automatisch via HA-API |
| Kiosk-fähig | Android-Kiosk-Modus oder einfach Vollbild + kein Zurück-Button |
| Zukunftssicher | Flutter läuft ggf. auch auf iOS, wenn weitere Geräte dazukommen |
| Offline-Anzeige | App kann Status cachen, auch wenn HA kurz nicht erreichbar ist |

#### Setup-Wizard (einmalig, läuft auf dem Tablet)

Der Elternteil richtet die App einmalig auf jedem Tablet ein – die App erledigt den Rest selbst:

```
Schritt 1: HA-URL eingeben
  ┌──────────────────────────────┐
  │  HA-Adresse:                 │
  │  [ http://192.168.1.10:8123] │
  │                              │
  │           [Weiter]           │
  └──────────────────────────────┘

Schritt 2: Admin-Login (einmalig, nur für Setup)
  ┌──────────────────────────────┐
  │  Benutzername: [admin      ] │
  │  Passwort:     [**********] │
  │                              │
  │  ⚠ Wird nur einmalig für    │
  │  die Einrichtung verwendet.  │
  │           [Anmelden]         │
  └──────────────────────────────┘

Schritt 3: Kind auswählen
  ┌──────────────────────────────┐
  │  Dieses Tablet gehört:       │
  │                              │
  │  ○ Ronja                     │
  │  ● Emilio                    │
  │  ○ Lennard                   │
  │                              │
  │  (Kinder von FamilyLink      │
  │   automatisch erkannt)       │
  │           [Einrichten]       │
  └──────────────────────────────┘

Schritt 4: App richtet automatisch ein:
  ✓ HA-Benutzer "tabletapp_emilio" erstellt
  ✓ Eingeschränkten Long-lived Token generiert
  ✓ input_number.zeitkonto_emilio gefunden/angelegt
  ✓ FamilyLink-Gerät für dieses Tablet erkannt
  ✓ Admin-Credentials gelöscht – nur Kind-Token bleibt
  ✓ Fertig!
```

#### Was die App automatisch per HA-API einrichtet

1. **Admin-Token holen** via `POST /auth/token` (OAuth password grant)
2. **HA-Benutzer anlegen** via WebSocket API: `auth/create_user`
3. **Long-lived Token für Kind-User erstellen** via WebSocket: `auth/long_lived_access_token`
4. **`input_number.zeitkonto_{kind}` prüfen** – falls nicht vorhanden: via `helpers` API anlegen
5. **FamilyLink-Gerät-ID ermitteln** – aus den HA-Entitäten (`sensor.*_screen_time`) das passende Gerät für dieses Tablet herauslesen (ggf. aus einer Liste wählen lassen)
6. **Konfiguration lokal speichern** (SharedPreferences/SecureStorage): Kind-Token, HA-URL, child_id, device_id
7. **Admin-Credentials verwerfen** – niemals persistent speichern

#### UI (Normalbetrieb, einfach halten)

```
┌─────────────────────────────┐
│   🕒  Emilios Zeitkonto     │
│                             │
│        ⏱  45 Minuten        │
│           Guthaben          │
│                             │
│  ┌────────┐  ┌────────┐     │
│  │ 15 min │  │ 30 min │     │
│  └────────┘  └────────┘     │
│  ┌────────┐  ┌────────┐     │
│  │ 45 min │  │ 60 min │     │
│  └────────┘  └────────┘     │
│                             │
│  Heute gebucht:   30 min    │
│  Aktuelles Limit: 90 min    │
└─────────────────────────────┘
```

Kein dauerhafter Login – die App startet direkt im Konto-Bildschirm.  
Buchungsbuttons sind ausgegraut wenn Guthaben < Betrag.  
Nach Buchung: kurze Bestätigungsanimation + Guthaben aktualisiert.

---

### 4. Authentifizierung

**Kein manuelles Token-Management** – der Setup-Wizard erledigt alles:

| Phase | Wer | Was |
|---|---|---|
| Setup | Admin | Gibt HA-URL + Admin-Credentials in die App ein |
| Setup | App (auto) | Erstellt HA-Benutzer `tabletapp_{kind}` per WebSocket API |
| Setup | App (auto) | Generiert Long-lived Token für diesen Nutzer |
| Setup | App (auto) | Speichert Token sicher in Android SecureStorage (EncryptedSharedPreferences) |
| Setup | App (auto) | Löscht Admin-Credentials aus dem Arbeitsspeicher |
| Betrieb | App | Verwendet nur den eingeschränkten Kind-Token für alle API-Calls |

**Berechtigungen des Kind-Tokens:**
- `input_number.zeitkonto_{kind}` lesen
- `script.buche_tabletzeit` aufrufen
- `number.familylink_*_{device_id}_today_limit` lesen (Status-Anzeige)
- `sensor.familylink_*_{device_id}_screen_time` lesen

HA unterstützt noch keine feingranularen Berechtigungen per Token nativ.  
Lösung: Ein eigener HA-Nutzer mit der Rolle **"User"** (nicht Admin) darf über normale HA-Mechanismen keine sicherheitskritischen Aktionen ausführen.  
Das Buchungs-Script prüft zusätzlich intern, ob der aufrufende User-Token zum richtigen Kind passt.

---

### 5. Buchungsfluss (Sequenz)

```
Kind                    Tablet-App              Home Assistant
 │                          │                        │
 │  Tippt "30 min buchen"   │                        │
 │─────────────────────────▶│                        │
 │                          │  GET /api/states/      │
 │                          │  input_number.zeitkonto│
 │                          │───────────────────────▶│
 │                          │◀───────────────────────│
 │                          │  state: "120"          │
 │                          │                        │
 │  Zeigt: "30 min buchen?  │                        │
 │  Verbleibend: 90 min"    │                        │
 │◀─────────────────────────│                        │
 │                          │                        │
 │  Bestätigt               │                        │
 │─────────────────────────▶│                        │
 │                          │  POST /api/services/   │
 │                          │  script/buche_tablet   │
 │                          │  {kind:"ronja",        │
 │                          │   device_id:"...",     │
 │                          │   minuten: 30}         │
 │                          │───────────────────────▶│
 │                          │                        │─┐ Prüft Guthaben
 │                          │                        │ │ Setzt Limit
 │                          │                        │◀┘ Bucht ab
 │                          │◀───────────────────────│
 │                          │  200 OK                │
 │                          │                        │
 │  "✓ 30 Minuten gebucht!" │                        │
 │◀─────────────────────────│                        │
```

---

### 6. Eltern-Verwaltung (Gutschrift)

Über das HA-Dashboard (Lovelace) können Eltern Guthaben aufbuchen:

- **Manuell:** `input_number`-Slider oder Eingabefeld im Dashboard
- **Automatisiert (future):** Automation basierend auf Ereignissen:
  - Kalender-Eintrag "Ronja hat gelesen" → +15 min
  - Bestimmter NFC-Tag gescannt → +20 min
  - TODO-Liste in HA abgehakt → +X min
- **Via Handy:** HA Companion App → Lovelace → "Guthaben aufbuchen"-Karte

---

## Implementierungsphasen

### Phase 1 – Grundgerüst (HA-Only, kein Flutter)
- [ ] `input_number`-Entitäten für jedes Kind anlegen (Helpers UI)
- [ ] HA-Script `script.buche_tabletzeit` schreiben (YAML)
- [ ] Script in DevTools testen: Guthaben lesen, Limit setzen, abbuchen
- [ ] Einfaches Lovelace-Dashboard für Eltern (Guthaben-Ansicht + manuelles Aufbuchen)

### Phase 2 – Flutter App (Basis)
- [ ] Flutter-Projekt anlegen (`tablet_time_app/`)
- [ ] Setup-Wizard implementieren:
  - [ ] HA-URL Eingabe + Verbindungstest
  - [ ] Admin-Login via `POST /auth/token`
  - [ ] FamilyLink-Kinder aus HA-Entities auslesen
  - [ ] Kind auswählen
  - [ ] HA-Benutzer + Token per WebSocket API erstellen
  - [ ] `input_number` prüfen / anlegen
  - [ ] FamilyLink device_id zuweisen (aus Liste wählen)
  - [ ] Admin-Credentials verwerfen, Kind-Token in SecureStorage speichern
- [ ] Hauptbildschirm:
  - [ ] Guthaben lesen + anzeigen
  - [ ] Buchungsbuttons (15/30/45/60 min)
  - [ ] Bestätigungsdialog
  - [ ] Heute gebuchte Zeit + aktuelles Tageslimit anzeigen
- [ ] Fehlerbehandlung: kein Guthaben, HA nicht erreichbar

### Phase 3 – Verfeinerung
- [ ] Buchungs-Log (wann wurde was gebucht)
- [ ] Push-Benachrichtigung an Eltern bei Buchung
- [ ] Wochenlimit: nicht mehr als X Minuten pro Woche buchbar
- [ ] Rollover-Logik (Nacht-Reset für "heute gebucht")
- [ ] APK-Verteilung / Update-Mechanismus
- [ ] Kiosk-Modus (Vollbild, kein Zurück, kein Task-Switcher)

### Phase 4 – Automatisierte Gutschriften (Eltern-Seite)
- [ ] NFC-Tag scannen → +X Minuten
- [ ] Kalender-Eintrag "Gelesen" → +15 min
- [ ] HA-Todo abgehakt → +X min
- [ ] Lovelace-Karte "Guthaben aufbuchen" mit Vorschlägen (Lesen, Helfen, Lernen)

---

## Offene Fragen

| # | Frage | Optionen |
|---|---|---|
| 1 | Wie verhalten sich bereits laufende Family-Link-Limits? Addiert die Buchung auf das bestehende Tageslimit oder ersetzt es? | **Addieren** erscheint natürlicher – Kind hat bereits 60 min, bucht 30 min → neues Limit = 90 min |
| 2 | Was passiert wenn das Kind schon mehr Zeit verbraucht hat als das neue Limit? | Limit auf `aktuell_verbraucht + betrag` setzen (nie kleiner als verbraucht) |
| 3 | Kann ein Kind mehrmals am Tag buchen? | Ja, solange Guthaben reicht. Max. Tageslimit = 720 min (Family Link Maximum) |
| 4 | Soll nicht verbrauchtes Tageslimit ans Guthaben zurückfließen? | Kompliziert (Tracking nötig); erstmal: **Nein**, Guthaben wird beim Buchen abgezogen, Ende |
| 5 | Wie wird die App vor unbeabsichtigter Nutzung durch andere geschützt? | Gerät ist dem Kind eindeutig zugeordnet; Token im Config nur für dieses Kind |
| 6 | Soll es ein Maximal-Guthaben geben (Deckel)? | Empfehlung: Ja, 600 min (10 h) als Obergrenze |
| 7 | Welche Buchungsschritte sind sinnvoll? | 15, 30, 45, 60 min; ggf. frei eingebbar |
| 8 | Guthaben übertragbar zwischen Kindern? | Nein, erstmal nicht |

---

## Datenmodell

```yaml
# input_number (Phase 1 - YAML oder Helpers UI)
input_number:
  zeitkonto_ronja:
    name: "Zeitkonto Ronja"
    min: 0
    max: 600
    step: 5
    unit_of_measurement: min
    icon: mdi:piggy-bank-outline

  zeitkonto_emilio:
    name: "Zeitkonto Emilio"
    min: 0
    max: 600
    step: 5
    unit_of_measurement: min
    icon: mdi:piggy-bank-outline

  zeitkonto_lennard:
    name: "Zeitkonto Lennard"
    min: 0
    max: 600
    step: 5
    unit_of_measurement: min
    icon: mdi:piggy-bank-outline
```

```yaml
# script.buche_tabletzeit (Entwurf)
script:
  buche_tabletzeit:
    alias: "Tabletzeit buchen"
    fields:
      kind:          # ronja | emilio | lennard
        selector:
          select:
            options: [ronja, emilio, lennard]
      device_id:     # opaque device ID aus FamilyLink
        selector:
          text:
      child_id:      # HA child_id aus FamilyLink
        selector:
          text:
      minuten:
        selector:
          number:
            min: 15
            max: 120
            step: 15
    sequence:
      # 1. Guthaben prüfen
      - condition: template
        value_template: >
          {{ states('input_number.zeitkonto_' ~ kind) | int >= minuten | int }}
      # 2. Aktuelles Limit lesen + erhöhen
      - service: number.set_value
        target:
          entity_id: "number.familylink_{{ child_id }}_{{ device_id }}_today_limit"
        data:
          value: >
            {{ (states('number.familylink_' ~ child_id ~ '_' ~ device_id ~ '_today_limit') | int)
               + (minuten | int) }}
      # 3. Guthaben abbuchen
      - service: input_number.set_value
        target:
          entity_id: "input_number.zeitkonto_{{ kind }}"
        data:
          value: >
            {{ (states('input_number.zeitkonto_' ~ kind) | int) - (minuten | int) }}
      # 4. Log-Eintrag
      - service: logbook.log
        data:
          name: "Zeitkonto {{ kind }}"
          message: "{{ minuten }} Minuten gebucht. Verbleibend: {{ (states('input_number.zeitkonto_' ~ kind) | int) }} min"
```

---

## Nächste Schritte

1. **Offene Fragen 1–3 klären** (Buchungslogik festlegen)
2. **Phase 1 starten:** `input_number`-Entitäten anlegen und Script in HA testen
3. **Flutter-Projekt anlegen** (`tablet_time_app/` im Repo oder separates Repo?)
4. **Entity-IDs der FamilyLink-Geräte ermitteln** (via Diagnosescript oder HA DevTools), damit die Script-Templates und der Setup-Wizard die richtigen IDs finden
5. **HA WebSocket API prüfen:** Kann ein Admin-Token wirklich neue User + Tokens per API anlegen? (Test in DevTools: `ws://ha:8123/api/websocket`, Message-Typ `auth/create_user`)

---

## HA WebSocket API – Relevante Calls für den Setup-Wizard

```json
// 1. Einloggen
{"type": "auth", "access_token": "<admin_token>"}

// 2. Benutzer anlegen
{"id": 1, "type": "config/auth/create", "name": "tabletapp_emilio", "group_ids": ["system-users"], "local_only": true}

// 3. Long-lived Token für neuen User erzeugen
//    (muss als dieser User authentifiziert sein – ggf. erst einloggen als neuer User)
{"id": 2, "type": "auth/long_lived_access_token", "client_name": "TabletApp Emilio", "lifespan": 3650}

// 4. input_number anlegen (falls nicht vorhanden)
{"id": 3, "type": "input_number/create", "name": "Zeitkonto Emilio", "min": 0, "max": 600, "step": 5}

// 5. Alle States lesen (um FamilyLink-Entities zu finden)
{"id": 4, "type": "get_states"}
```
