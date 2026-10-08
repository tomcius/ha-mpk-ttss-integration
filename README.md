# MPK Kraków (TTSS) — integracja Home Assistant

Odjazdy autobusów i tramwajów MPK Kraków, konfigurowane **w całości z UI** (bez YAML).

Dwa źródła naraz: `api.ttss.pl` (backend [beta.ttss.pl](https://beta.ttss.pl/)) daje
rzeczywiste odjazdy na 30 minut naprzód, a oficjalny **GTFS** z
[gtfs.ztp.krakow.pl](https://gtfs.ztp.krakow.pl) uzupełnia resztę doby z rozkładu.
Każdy odjazd niesie flagę `realtime`, więc widać, co jest potwierdzone, a co planowane.

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
| `departures` | `[{time: "17:50", line: "244", direction: "…", in_minutes: 11, realtime: true}, …]` |
| `next_two` | `"1. 11 min, 2. 35 min"` |
| `by_line` | `{"224": [{time, in_minutes, direction, realtime}, …], "244": […]}` — po dwa najbliższe odjazdy każdej linii |
| `directions` | `["Nowy Bieżanów Południe"]` — kierunki nadchodzących odjazdów |
| `stop_id` | `"017269"` |
| `stop_name` | `"Wieliczka Modrzewiowa"` |

### Przykład karty

```yaml
type: custom:mushroom-template-card
entity: sensor.wieliczka_modrzewiowa_017269
primary: Wieliczka Modrzewiowa
secondary: >-
  {% for line, deps in (state_attr(entity, 'by_line') or {}).items() %}
  {{ line }}: {{ deps | map(attribute='in_minutes') | join(', ') }} min
  {%- if not loop.last %} · {% endif %}
  {% else %}brak odjazdów{% endfor %}
icon: mdi:bus
icon_color: "{{ 'red' if states(entity) | int(99) < 5 else 'green' }}"
tap_action:
  action: more-info
```

## Rozkład z GTFS

Realtime sięga 30 minut naprzód (zmierzone, patrz niżej), co dla linii kursującej co
dwie godziny oznacza, że przez większość dnia jej nie widać. Dlatego integracja dociąga
rozkład z oficjalnego feedu GTFS.

**Jak to działa:** raz na dobę, w tle, pobierany jest archiwum GTFS i wyłuskiwane są
z niego wiersze wyłącznie tego przystanku (oraz wybranych linii, jeśli ustawiono filtr).
Rozkład uzupełnia listę **dopiero za ostatnim odjazdem znanym z realtime**, więc ten sam
kurs nie pojawia się dwa razy, nawet gdy jego rzeczywisty czas odbiega od rozkładowego.
Realtime zawsze ma pierwszeństwo.

**Koszt:** archiwum autobusowe to ~20 MB, a `stop_times.txt` rozpakowuje się do ~137 MB —
dlatego nie jest nigdzie zapisywany w całości, tylko strumieniowany, a zostają z niego
dziesiątki kilobajtów. Ekstrakcja trwa ~3 s na szybkim komputerze; na Raspberry Pi
należy się spodziewać kilkudziesięciu sekund. Dzieje się to w tle i nie blokuje
odczytów — do czasu wczytania rozkładu encja pokazuje samo okno realtime. Jedno
pobranie jest współdzielone przez wszystkie skonfigurowane przystanki.

**Zweryfikowane:** rozkład linii 224 dla peronu 017269 wyliczony z GTFS
(`06:08, 08:09, 10:19, 12:19, 14:19, 16:20, 18:19, 20:29, 22:30`) zgadza się co do minuty
z rozkładem na `mpk.krakow.pl`. Kursy po północy (GTFS zapisuje je jako `24:07`)
są mapowane na właściwy dzień.

## Ograniczenia

Wszystkie wynikają ze źródeł danych i żadnej nie da się obejść po stronie integracji.

- **Brak korekty czasu rzeczywistego.** API podaje tylko `time/line/direction` —
  bez pola opóźnienia. Minuty liczone są z podanej godziny odjazdu.
- **Okno sięga 30 minut do przodu.** Zmierzone: 25 próbek co minutę na jednym słupku.
  Odjazd o 19:38 pojawił się w odpowiedzi dokładnie o 19:08 i ani chwili wcześniej.
  Serwer trzyma też odjazd ~9 minut *po* jego godzinie (19:08 był widoczny do 19:17).
  Przy kursach co pół godziny oznacza to 1–2 pozycje w odpowiedzi — i linię, która
  jeździ rzadziej, widać dopiero na pół godziny przed odjazdem.
- **Nie istnieje endpoint z liniami przystanku** (`/lines/`, `/stopinfo/`, `/routes/`
  zwracają 404), więc pełnej listy linii obsługujących słupek nie można pobrać.
  Podpowiedzi w filtrze linii pochodzą wyłącznie z bieżącego okna i bywają niepełne —
  dlatego pole przyjmuje też numery wpisane ręcznie.
- **Pole `parent` nie jest grupą przystanku**, mimo że tak wygląda. To tylko prefiks
  numeru: pod `0172` znajduje się 18 słupków o 9 różnych nazwach (Krokusowa, Łagiewniki
  SKA, kilka przystanków w Wieliczce), oddalonych o kilometry. Numery tych wpisów
  zbiorczych nie są nawet unikalne. Odpytywanie ich zwraca odjazdy z niepowiązanych
  przystanków, więc integracja pyta wyłącznie o wybrany słupek.
- **Kierunek nie jest trwałą cechą słupka** — jeden słupek bywa obsługiwany w kilku
  kierunkach (`017269` to 224 → *Centrum JP II* oraz 244 → *Nowy Bieżanów Południe*).
  Dlatego nazwa encji zawiera numer słupka, a nie kierunek: kierunek znany w chwili
  konfiguracji byłby migawką i mylił przez resztę dnia. Aktualne kierunki są
  w atrybucie `directions`.
- API duplikuje każdy rekord; integracja deduplikuje je po `(godzina, linia, kierunek)`.
- Odpytywanie co 60 s.

### Pamięć odjazdów

Integracja pamięta odjazdy, które już zobaczyła, i trzyma je do czasu, aż miną.

**Nie rozszerza to 30-minutowego horyzontu** — pomiar pokazał, że serwer utrzymuje
odjazd w odpowiedzi nieprzerwanie od chwili, gdy wejdzie w okno, aż do kilku minut po
godzinie odjazdu, więc w normalnych warunkach nie ma czego ratować. Pamięć zabezpiecza
przed chwilowym zniknięciem pozycji z odpowiedzi; linii, której kurs jest odleglejszy
niż pół godziny, nie pokaże, bo API nigdy jej nie podało.

Cena: odwołany kurs pozostanie widoczny do swojej godziny odjazdu — bez danych czasu
rzeczywistego nie da się go odróżnić od kursu, który po prostu wypadł z odpowiedzi.
Pamięć żyje w RAM i zeruje się przy restarcie Home Assistanta.

Poza oknem realtime tę rolę przejmuje GTFS (sekcja wyżej).

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
