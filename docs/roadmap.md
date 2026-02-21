# HAFamilyLink – Entwicklungs-Roadmap

Stand: 21. Februar 2026 · Aktuelle Version: `0.4.3`

---

## Aktueller Stand (v0.4.3)

| Bereich | Status |
|---|---|
| Cookie-Authentifizierung (Playwright + manuell) | ✅ Vollständig |
| Session-Validierung & Re-Auth-Flow | ✅ Vollständig |
| HTTP 401 → Reauth-Trigger | ✅ Vollständig |
| Cookies als expliziter Header (kein CookieJar) | ✅ Vollständig |
| Echter kidsmanagement API-Client | ✅ Vollständig |
| Kinder als HA-Devices (switch platform) | ✅ Vollständig |
| Sensor-Platform (Bildschirmzeit pro Kind) | ✅ Vollständig |
| Number-Platform (App-Zeitlimits) | ✅ Vollständig |
| Options-Flow (Intervall, Timeout) | ✅ Vollständig |
| 7 LLM-Tools für AI-Conversation-Agents | ✅ Vollständig |
| Config-Flow (Setup + Re-Auth) | ✅ Vollständig |
| Tests (15/15 passing) | ✅ Vollständig |
| HACS-kompatibel | ✅ Vollständig |

---

## Phase 1 – Coordinator: Daten aller Kinder cachen

**Ziel:** Der Coordinator soll beim Poll nicht nur die Kinderliste holen,
sondern für jedes Kind auch App-Nutzung und Restriktionen cachen – damit
Sensor- und Number-Entities daraus lesen können, ohne eigene HTTP-Calls zu
machen.

**Dateien:** `coordinator.py`

**Änderungen:**

- `_async_update_data` erweitern: nach `async_get_members()` parallel pro Kind
  `async_get_apps_and_usage(child_id)` aufrufen (`asyncio.gather`).
- Rückgabe-Struktur ändern von `{"devices": [...]}` auf:

```python
{
    "children": [{"child_id": ..., "name": ..., "email": ...}, ...],
    "usage": {
        "child_id_1": [{"app_name": "YouTube", "usage_seconds": 1234}, ...],
        ...
    },
    "restrictions": {
        "child_id_1": {
            "limited": [{"app": "YouTube", "limit_minutes": 30}, ...],
            "blocked": ["TikTok", ...],
            "always_allowed": ["Calculator", ...],
        },
        ...
    },
}
```

- `update_interval` aus `entry.options` lesen (Fallback: `entry.data`,
  Fallback: `DEFAULT_UPDATE_INTERVAL`).
- Interner `_children`-Cache als `dict[str, dict]` (`child_id → child_data`)
  für schnellen Entity-Zugriff.

**Version:** `0.4.0`

---

## Phase 2 – Switch-Platform: Device Registry sauber aufräumen

**Ziel:** Jedes Kind soll als vollständiges HA-Device mit Metadaten erscheinen.
Der Switch-Zustand (locked/unlocked) ist über die kidsmanagement-API nicht
verfügbar – der Switch wird daher zum reinen Indikator „Supervision aktiv" (immer `True`/`on`).

**Dateien:** `switch.py`

**Änderungen:**

- Switch-Klasse umbenennen zu `FamilyLinkChildSwitch`.
- `DeviceInfo` ergänzen:

```python
DeviceInfo(
    identifiers={(DOMAIN, child_id)},
    name=child_name,
    manufacturer="Google",
    model="Supervised Child",
    configuration_url="https://families.google.com",
    entry_type=DeviceEntryType.SERVICE,
)
```

- `is_on` immer `True` (Supervision ist aktiv solange die Integration läuft).
- `icon` → `mdi:account-child`.
- `extra_state_attributes`: `child_id`, `email`.
- Daten aus `coordinator.data["children"]` lesen statt `coordinator.data["devices"]`.

**Version:** `0.4.0`

---

## Phase 8 – v0.5.0: Aktionen & Steuerung

### 8a – Bonus-Zeit gewähren

**Ziel:** Einmalig X Minuten extra Bildschirmzeit für ein Kind gewähren.

**Neue Entity:** `button.{child}_grant_bonus_time` + `number.{child}_bonus_minutes` (5–120 min, Schritt 5)

**API:** `POST /people/{child_id}/apps:updateRestrictions` mit temporärem Limit-Erhöhung

**Version:** `0.5.0`

---

### 8b – App blockieren / entsperren als Button

**Ziel:** Einzelne Apps direkt aus HA sperren oder freigeben.

**Neue Entities pro geblockte App:**
- `button.{child}_{app}_unblock` – App entsperren
- `button.{child}_{app}_block` – App blockieren (für alle nicht-geblockte Apps)

**Version:** `0.5.0`

---

### 8c – Schlafenszeit lesen & setzen

**Ziel:** Bedtime-Schedule als `time`-Entity in HA.

**Neue Entities:**
- `time.{child}_bedtime_start`
- `time.{child}_bedtime_end`

**API:** Bedtime-Schedule-Endpoint prüfen (aus Browser-DevTools ableiten)

**Version:** `0.5.0`

---

## Phase 3 – Sensor-Platform: Bildschirmzeit & App-Nutzung *(erledigt)*

**Ziel:** Pro Kind zwei Sensoren, die aus dem Coordinator-Cache gelesen werden.

**Neue Datei:** `sensor.py`

**Entities:**

| Entity-ID | Geräteklasse | Einheit | Beschreibung |
|---|---|---|---|
| `sensor.{name}_screen_time_today` | `duration` | `min` | Gesamte Bildschirmzeit heute (Summe aller Apps) |
| `sensor.{name}_most_used_app` | – | – | Name der App mit der höchsten heutigen Nutzungszeit |

**Umsetzung:**

```python
class FamilyLinkScreenTimeSensor(CoordinatorEntity, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION

    @property
    def native_value(self) -> int:
        usage = self.coordinator.data.get("usage", {}).get(self._child_id, [])
        return sum(e["usage_seconds"] for e in usage) // 60
```

- `__init__.py`: `Platform.SENSOR` zu `PLATFORMS` hinzufügen.
- `hacs.json`: `"domains"` um `"sensor"` erweitern.

**Version:** `0.4.0`

---

## Phase 4 – Number-Platform: App-Zeitlimits steuern *(erledigt)*

**Ziel:** Apps mit gesetztem Tageslimit als `NumberEntity` darstellbar und
direkt aus HA heraus änderbar.

**Neue Datei:** `number.py`

**Entity pro (Kind, App) mit bekanntem Limit:**

| Attribut | Wert |
|---|---|
| `native_min_value` | `0` (0 = Limit entfernen) |
| `native_max_value` | `1440` |
| `native_step` | `5` |
| `native_unit_of_measurement` | `min` |
| `icon` | `mdi:timer` |

```python
async def async_set_native_value(self, value: float) -> None:
    if value == 0:
        await self.coordinator.async_remove_app_limit(self._child_id, self._app_name)
    else:
        await self.coordinator.async_set_app_limit(self._child_id, self._app_name, int(value))
    await self.coordinator.async_request_refresh()
```

- Entities werden dynamisch aus `coordinator.data["restrictions"][child_id]["limited"]`
  erzeugt. Bei jedem Update werden neue Apps hinzugefügt / entfernte entfernt
  (`async_add_entities` mit `update_before_add=True`).
- `__init__.py`: `Platform.NUMBER` zu `PLATFORMS` hinzufügen.

**Version:** `0.4.0`

---

## Phase 5 – Options-Flow

**Ziel:** `update_interval` und `timeout` nach dem Setup änderbar machen.
Außerdem: LLM-API-Auswahl für Conversation-Agents direkt in den Options.

**Dateien:** `config_flow.py`

**Neue Klasse:**

```python
class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_UPDATE_INTERVAL, ...): vol.All(int, vol.Range(30, 3600)),
                vol.Optional(CONF_TIMEOUT, ...): vol.All(int, vol.Range(10, 120)),
                vol.Optional(CONF_LLM_HASS_API, ...): SelectSelector(...),
            }),
        )
```

- `ConfigFlow` um `async_get_options_flow` ergänzen.
- `coordinator.py`: `update_interval` bei Options-Änderung live aktualisieren
  via `entry.add_update_listener`.
- `strings.json` + `translations/en.json`: Options-Flow-Keys ergänzen.

**Version:** `0.4.0`

---

## Phase 6 – Tests

**Ziel:** Mindest-Testabdeckung für alle kritischen Pfade.

**Neue Dateien unter `tests/`:**

| Datei | Was getestet wird |
|---|---|
| `test_config_flow.py` | Cookie-Eingabe (Mock `SessionManager`), Reauth-Flow |
| `test_coordinator.py` | `_async_update_data` mit gemocktem `FamilyLinkClient` |
| `test_llm_api.py` | Alle 7 Tools mit Beispiel-Fixtures, Fehlerfall |
| `test_client.py` | `_sapisidhash()` Berechnung, `_resolve_package()`, HTTP-Fehlerbehandlung |
| `test_sensor.py` | `native_value` Berechnung aus gemockten Coordinator-Daten |

**Abhängigkeiten** (bereits in `requirements-dev.txt`):
- `pytest-asyncio`
- `pytest-homeassistant-custom-component`

**Version:** `0.4.0`

---

## Phase 7 – Abschluss: i18n + hacs.json

**Ziel:** Alle neuen Strings lokalisiert, `hacs.json` aktuell.

**Änderungen:**

- `strings.json` + `translations/en.json`:
  - Options-Flow-Step `init` mit `update_interval`, `timeout`, `llm_hass_api`
  - Sensor-Entity-Beschreibungen
  - Number-Entity-Beschreibungen
- `hacs.json`: `"domains": ["switch", "sensor", "number"]`
- `manifest.json`: Version auf `0.4.0` bumpen

**Version:** `0.4.0`

---

## Zusammenfassung Versionsplan

| Version | Inhalt |
|---|---|
| **0.3.0** *(released)* | Echter API-Client, 7 LLM-Tools, Cookie-Auth |
| **0.4.x** *(released)* | Sensor + Number Entities, Options-Flow, Tests, Cookie-Header-Fix |
| **0.5.0** | Bonus-Zeit, App-Block/Unblock-Buttons, Bedtime-Entities |
| **1.0.0** | HACS Default Repository Submission |

---

## Reihenfolge der Implementierung

```
Phase 1 (Coordinator)
    → Phase 2 (Switch fix)
    → Phase 3 (Sensor)
        → Phase 4 (Number)
            → Phase 5 (Options-Flow)
                → Phase 6 (Tests)
                    → Phase 7 (i18n + hacs.json)
                        → Release 0.4.0
```
