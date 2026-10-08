# MPK Kraków (TTSS) — integracja Home Assistant

Najbliższe odjazdy autobusów i tramwajów MPK Kraków, konfigurowane **w całości z UI**
(bez YAML). Dane pochodzą z `api.ttss.pl` — backendu, na którym stoi
[beta.ttss.pl](https://beta.ttss.pl/).

## Dlaczego nie istniejące integracje

Dostępne komponenty MPK-KR odpytują `ttss.mpk.krakow.pl/internetservice`, które
**nie działa** — zwraca stronę HTML zamiast JSON-a. Dodatkowo oczekują ID przystanków
z zupełnie innej numeracji niż ta, którą pokazuje dzisiejsze TTSS.

Ta integracja używa czynnego API i rozwiązuje ID po nazwie, więc nie trzeba ich nigdzie
ręcznie szukać.

## Instalacja

**HACS** → ⋮ → *Custom repositories* → URL tego repo, kategoria *Integration* →
*Download* → restart Home Assistanta.

**Ręcznie:** skopiuj `custom_components/mpk_ttss` do `/config/custom_components/`
i zrestartuj Home Assistanta.

## Konfiguracja

*Ustawienia → Urządzenia i usługi → Dodaj integrację → **MPK Kraków (TTSS)***

1. **Rodzaj pojazdu** — autobus albo tramwaj (TTSS trzyma je w osobnych zbiorach).
2. **Nazwa przystanku** — fragment wystarczy, np. `Wieliczka Modrz`.
3. **Słupek** — lista pokazuje kierunek każdego słupka, np.
   `Wieliczka Modrzewiowa → Nowy Bieżanów Południe [017269]`.
   Dzięki temu nie trzeba zgadywać, który numer to który kierunek.
4. **Filtr linii** — opcjonalny; puste = wszystkie linie.

Jeden wpis = jeden słupek = jeden kierunek. Dla drugiego kierunku dodaj integrację
ponownie i wybierz drugi słupek. Filtr linii można później zmienić przez *Konfiguruj*
bez usuwania wpisu.

## Encja

Stan to **liczba minut do najbliższego odjazdu** (jednostka `min`), więc działa
z progami i warunkami numerycznymi w automatyzacjach.

| Atrybut | Przykład |
|---|---|
| `departures` | `[{time: "17:50", line: "244", direction: "Nowy Bieżanów Południe", in_minutes: 11}, …]` |
| `next_two` | `"1. 11 min, 2. 35 min"` |
| `stop_id` | `"017269"` |
| `stop_name` | `"Wieliczka Modrzewiowa"` |
| `direction` | `"Nowy Bieżanów Południe"` |

### Przykład karty

```yaml
type: custom:mushroom-template-card
entity: sensor.wieliczka_modrzewiowa_nowy_biezanow_poludnie
primary: Wieliczka Modrzewiowa
secondary: "{{ state_attr(entity, 'next_two') }}"
icon: mdi:bus
icon_color: "{{ 'red' if states(entity) | int(99) < 5 else 'green' }}"
tap_action:
  action: more-info
```

## Ograniczenia

- **Brak korekty czasu rzeczywistego.** API podaje tylko `time/line/direction` —
  nie ma informacji o opóźnieniach. Minuty liczone są z rozkładowej godziny odjazdu.
- **API zwraca tylko kilka najbliższych odjazdów**, nie cały dzienny rozkład.
  Atrybut `departures` zawiera tyle, ile udostępnia serwer (zwykle 1–3 pozycje).
- API duplikuje każdy rekord; integracja deduplikuje je po `(godzina, linia, kierunek)`.
- Odpytywanie co 60 s.

## Podziękowania

API i dane: projekt [`jacekkow/mpk-ttss`](https://github.com/jacekkow/mpk-ttss).
