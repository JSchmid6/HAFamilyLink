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
                          REST API
                    (Long-lived Token)
                               │
              ┌────────────────┴────────────────┐
              │                                 │
   ┌──────────▼──────────┐           ┌──────────▼──────────┐
   │   Ronja's Tablet    │           │   Emilio's Tablet   │
   │                     │           │                     │
   │  ┌───────────────┐  │           │  ┌───────────────┐  │
   │  │  Buchungs-App │  │           │  │  Buchungs-App │  │
   │  │  (PWA/Kiosk)  │  │           │  │  (PWA/Kiosk)  │  │
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

#### Technologie-Optionen

| Option | Aufwand | Vorteile | Nachteile |
|---|---|---|---|
| **HA Companion App + Lovelace-Panel** (eigene View) | Gering | Kein Extra-Code, HA-Auth | Companion-App nötig, voller HA-Zugriff wenn unvorsichtig |
| **PWA (eigene statische Webseite)** | Mittel | Kiosk-fähig, minimales UI, nur REST-Calls | Hosting nötig (HA Static Files oder externer Server) |
| **Custom HA Panel (iframe)** | Mittel | In HA integriert, eigenes UI möglich | Mehr Setup |
| **Android-App (Kotlin/Flutter)** | Hoch | Native, Offline-Fähigkeit | Sehr viel Aufwand |

→ **Empfehlung: PWA**, gehostet als statische Seite direkt in HA unter `www/tablettime/index.html`. Kein Webserver nötig, erreichbar unter `http://homeassistant.local:8123/local/tablettime/`.

#### UI (einfach halten)

```
┌─────────────────────────┐
│   🕒 Ronja's Zeitkonto  │
│                         │
│      ⏱ 120 Minuten      │
│         Guthaben        │
│                         │
│  [ 15 min ]  [ 30 min ] │
│  [ 45 min ]  [ 60 min ] │
│                         │
│   Heute gebucht: 0 min  │
│   Limit heute: 60 min   │
└─────────────────────────┘
```

Kein Login-Formular – die App ist gerätespezifisch (Token ist in der App hinterlegt).

---

### 4. Authentifizierung

- Pro Kind/Gerät wird ein **HA-Benutzer mit eingeschränkten Rechten** angelegt.
- Für diesen Benutzer wird ein **Long-Lived Access Token** generiert.
- Der Token wird einmalig in der App-Config hinterlegt (z.B. als JS-Konstante in der HTML-Seite oder als `config.json` neben `index.html`).
- Der Token gibt nur Zugriff auf:
  - `input_number.zeitkonto_{kind}` (read-only)
  - `script.buche_tabletzeit` (call only)
  - `sensor.familylink_*_{device_id}_*` (read-only, für aktuelles Limit)

**Offene Frage:** HA unterstützt noch keine feingranularen Berechtigungen pro Token standardmäßig. Optionen:
- Eigene HA-User-Gruppe (erfordert `auth` in `configuration.yaml`)
- Token-Validierung im Script selbst (prüfen welcher User den Call auslöst)
- API-Proxy (kleines Middleware-Script, das nur bestimmte Calls durchlässt)
→ Erstmal pragmatisch: separater HA-Nutzer mit "nur Home Assistant"-Rolle, Token in App.

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

### Phase 1 – Grundgerüst (HA-Only, kein Code)
- [ ] `input_number`-Entitäten für jedes Kind anlegen (Helpers UI)
- [ ] HA-Script `script.buche_tabletzeit` schreiben (YAML)
- [ ] Script testet in DevTools: Guthaben lesen, Limit setzen, abbuchen
- [ ] Einfaches Lovelace-Dashboard für Eltern (Guthaben-Ansicht + manuelles Aufbuchen)

### Phase 2 – Tablet-App (PWA)
- [ ] `www/tablettime/index.html` + `config.json` erstellen
- [ ] Kind-spezifischer HA-Benutzer + Long-lived Token
- [ ] App zeigt Guthaben und aktuelles Tageslimit
- [ ] Buchungsbuttons (15/30/45/60 min) → rufen Script auf
- [ ] Bestätigungsdialog vor Buchung
- [ ] Fehleranzeige bei leerem Konto

### Phase 3 – Verfeinerung
- [ ] Buchungs-Log (wann wurde was gebucht) – via `logbook` oder `history`
- [ ] Push-Benachrichtigung an Eltern bei Buchung
- [ ] Rollover: nicht verbrauchtes Tageslimit verfällt (Nacht-Reset)
- [ ] Wochenlimit: nicht mehr als X Minuten pro Woche buchbar
- [ ] Automatisierte Gutschriften (NFC, Kalender, Checkliste)

### Phase 4 – Integration in FamilyLink-Custom-Component (optional)
- [ ] Zeitkonto als eigene Sensor-/Number-Entität direkt in der Integration
- [ ] Persistenz über HA-Storage statt `input_number`
- [ ] Buchungs-Service als registrierter HA-Service im DOMAIN

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
3. **Tablet-App skizzieren** – welches Gerät, wie soll der Kiosk-Modus aussehen?
4. **Entity-IDs der FamilyLink-Geräte ermitteln** (via Diagnosescript oder HA DevTools), damit die Script-Templates stimmen
