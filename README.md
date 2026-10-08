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
3. **Słupek** — lista pokazuje kierunki widoczne na każdym słupku, np.
   `Wieliczka Modrzewiowa → Nowy Bieżanów Południe [017269]`.
   Dzięki temu widać, który numer odpowiada której stronie ulicy.
4. **Filtr linii** — opcjonalny; puste = wszystkie linie. Podpowiedzi to nadzbiór
   (patrz *Ograniczenia*), można też wpisać numer linii z ręki.

Jeden wpis = jeden słupek. Dla przeciwnego kierunku dodaj integrację ponownie
i wybierz drugi słupek. Filtr linii zmienisz później przez *Konfiguruj*, bez
usuwania wpisu.

## Encja

Stan to **liczba minut do najbliższego odjazdu** (jednostka `min`), więc działa
z progami i warunkami numerycznymi w automatyzacjach.

| Atrybut | Przykład |
|---|---|
| `departures` | `[{time: "17:50", line: "244", direction: "Nowy Bieżanów Południe", in_minutes: 11}, …]` |
| `next_two` | `"1. 11 min, 2. 35 min"` |
| `directions` | `["Nowy Bieżanów Południe"]` — kierunki nadchodzących odjazdów |
| `stop_id` | `"017269"` |
| `stop_name` | `"Wieliczka Modrzewiowa"` |

### Przykład karty

```yaml
type: custom:mushroom-template-card
entity: sensor.wieliczka_modrzewiowa_017269
primary: Wieliczka Modrzewiowa
secondary: "{{ state_attr(entity, 'next_two') }}"
icon: mdi:bus
icon_color: "{{ 'red' if states(entity) | int(99) < 5 else 'green' }}"
tap_action:
  action: more-info
```

## Ograniczenia

Wszystkie wynikają z samego API i żadnej nie da się obejść po stronie integracji.

- **Brak korekty czasu rzeczywistego.** API podaje tylko `time/line/direction` —
  bez opóźnień. Minuty liczone są z rozkładowej godziny odjazdu.
- **Okno jest wąskie i przesuwa się.** Serwer zwraca zwykle 1–3 najbliższe odjazdy,
  nie dzienny rozkład. Ten sam słupek o 18:28 pokazywał linie 224 i 244, a o 18:32
  już tylko 244 — nie dlatego, że 224 tam nie jeździ, ale dlatego, że wypadła z okna.
- **Nie istnieje endpoint z liniami przystanku** (`/lines/`, `/stopinfo/`, `/routes/`
  zwracają 404), więc pełnej listy linii obsługujących słupek nie można pobrać.
  Podpowiedzi w filtrze linii pochodzą ze słupka **i z grupy przystanków**, czyli są
  nadzbiorem — mogą zawierać linię, która zatrzymuje się po drugiej stronie ulicy.
- **Kierunek nie jest trwałą cechą słupka** — jeden słupek bywa obsługiwany w kilku
  kierunkach (`017269` to 224 → *Centrum JP II* oraz 244 → *Nowy Bieżanów Południe*).
  Dlatego nazwa encji zawiera numer słupka, a nie kierunek: kierunek znany w chwili
  konfiguracji byłby migawką i mylił przez resztę dnia. Aktualne kierunki są
  w atrybucie `directions`.
- API duplikuje każdy rekord; integracja deduplikuje je po `(godzina, linia, kierunek)`.
- Odpytywanie co 60 s.

## Logo

`custom_components/mpk_ttss/brand/` zawiera `icon.png` (256×256, sam herb) i
`logo.png` (192×128, pełne logo) w formacie wymaganym przez
[home-assistant/brands](https://github.com/home-assistant/brands). Home Assistant
serwuje ikony integracji wyłącznie z tamtego repozytorium, więc żeby pojawiły się
w interfejsie, trzeba je tam zgłosić osobnym PR-em — obecność plików w tym repo
sama z siebie ich nie wyświetli.

Źródło: [mpk.krakow.pl](https://mpk.krakow.pl/images/logo.svg). Znak towarowy
należy do MPK S.A. w Krakowie i jest użyty wyłącznie do identyfikacji integracji.

## Podziękowania

API i dane: projekt [`jacekkow/mpk-ttss`](https://github.com/jacekkow/mpk-ttss).
