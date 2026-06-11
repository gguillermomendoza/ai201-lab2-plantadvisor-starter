# Spec: Tool Functions

**File:** `tools.py`
**Status:** `get_seasonal_conditions` — Pre-implemented, read through. `lookup_plant` — complete spec fields before implementing.

---

## Purpose

These two functions are the tools the agent can call. They retrieve structured data from the local plant database and seasonal data files and return it to the agent loop, which passes it to the LLM as context for generating a response.

---

## Function 1: `lookup_plant()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `plant_name` | `str` | The plant name as entered by the user or chosen by the LLM — may be any casing, common name, scientific name, or alias |

**Output:** `dict`

When the plant is **found**, return:
```python
{"found": True, "plant": <the full plant dict from _plant_db>}
```

When the plant is **not found**, return:
```python
{"found": False, "name": <normalized input>, "message": <helpful string>}
```

---

### Design Decisions

*Complete the two blank fields below before writing code. The others are pre-filled for you.*

---

#### Input normalization

Strip leading/trailing whitespace and convert to lowercase before any comparison.

```python
normalized = plant_name.strip().lower()
```

---

#### Search order

Search in this order: direct key → display name → aliases. Keys are the fastest
lookup (O(1) dict access), so check those first. Display names are the next most
likely match for clean user input. Aliases are the broadest net, so they go last.

```
1. Direct key match: normalized in _plant_db
2. Display name match: plant["display_name"].lower() == normalized
3. Alias match: normalized in [alias.lower() for alias in plant["aliases"]]
```

---

#### Alias matching approach

*Aliases are stored as a list of strings. How will you check if the normalized input matches any alias in the list? Write your approach in pseudocode or plain English.*

```
For each plant, lowercase every alias and build a list, then test membership:
    if normalized in [alias.lower() for alias in plant["aliases"]]
This is case-insensitive and matches the whole alias string exactly (after the
input was already stripped + lowercased). Use a generator with any() so we stop
at the first match:
    if any(normalized == alias.lower() for alias in plant.get("aliases", []))
.get with a default guards plants that have no aliases key.
```

---

#### Not-found message

*When a plant isn't found, the agent will read your message and use it to decide what to tell the user. Write the exact string you'll return — make it useful to the agent, not just to a human reading logs.*

```
"No plant matching '<normalized>' was found in the database. The database
contains these plants: <comma-separated display names>. Ask the user to pick one
of these, or to clarify the plant name (common or scientific) if they meant
something else."

The message tells the agent (1) what was searched for, (2) the full set of plants
it CAN answer about, and (3) what to do next — so it won't hallucinate care advice
for an unknown plant and can offer the user real options.
```

---

#### Implementation Notes

*Fill this in after implementing and running the app.*

**Test: does `"devil's ivy"` return the pothos entry?**
```
yes — matched via the alias list (case-insensitive).
```

**Test: does `"SNAKE PLANT"` return the snake plant entry?**
```
yes — input is lowercased to "snake plant" and matched against display_name.
Note the direct key is "snake_plant" (underscore), so this hits step 2, not step 1.
```

**One edge case you discovered while implementing:**
```
The display-name form "snake plant" (space) is NOT the same as the db key
"snake_plant" (underscore), so a key-only lookup would miss it. The display_name
and alias passes are what catch human-typed names. Also guarded plants that lack
an "aliases" or "display_name" key with .get(..., default) so the scan never
raises a KeyError.
```

---

## Function 2: `get_seasonal_conditions()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `season` | `str \| None` | One of `"spring"`, `"summer"`, `"fall"`, `"winter"`, or `None` to auto-detect |

**Output:** `dict`

The full season dict from `_season_data`, plus one additional field:

| Added field | Type | Value |
|-------------|------|-------|
| `"detected_season"` | `bool` | `True` if auto-detected from the month; `False` if season was passed as an argument |

---

### Design Decisions

*This function is pre-implemented — read through these fields and the code before working on `lookup_plant`.*

---

#### Auto-detection logic

When `season` is `None`, get the current calendar month with `datetime.now().month`
and look it up in the `_MONTH_TO_SEASON` dict, which maps month numbers to season strings.

```python
current_month = datetime.now().month
season_key = _MONTH_TO_SEASON[current_month]
```

---

#### Season validation

If the caller passes an invalid season string (e.g., `"monsoon"`), the function
falls back to auto-detection — same as if `None` were passed. The `VALID_SEASONS`
set acts as the gate:

```python
VALID_SEASONS = {"spring", "summer", "fall", "winter"}
if season and season.lower() in VALID_SEASONS:
    ...  # use provided season
else:
    ...  # auto-detect
```

---

#### Return structure

The full season dict from `_season_data`, plus a `detected_season` boolean. Example for spring:

```python
{
    "season": "spring",
    "watering": "Increase watering frequency as plants break dormancy ...",
    "fertilizing": "Resume feeding with a balanced fertilizer ...",
    "light": "Days are lengthening — move plants closer to windows ...",
    "pests": "Watch for spider mites and aphids as temperatures rise ...",
    "detected_season": True   # True = auto-detected; False = caller specified
}
```

---

#### Implementation Notes

*Fill this in after testing.*

**Test: does calling with `season=None` return the correct season for the current month?**
```
Current month: [month]
Expected season: [season]
Returned season: [season]
```

**Test: does calling with `season="winter"` return winter data regardless of the current month?**
```
[yes / no]
```
