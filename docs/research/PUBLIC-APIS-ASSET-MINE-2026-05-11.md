# Public-APIs Asset Mine

> **Source:** `public-apis/public-apis` (github.com/public-apis/public-apis, 434k stars, MIT, indexed 2026-05-11).
> **Mined by:** assetboi ride-along R1a (BOSS micro-steal 2026-05-11).
> **Goal:** 5-10 NEW asset-relevant free APIs FAW could wrap beyond existing
> PolyHaven / Fab / Epic / Unity / ComfyUI / Mixamo / Kenney / AmbientCG /
> FreeSound / Quaternius / Stable Audio.
>
> Filter: free-tier exists, non-paywalled, asset-relevant (art, audio, models,
> game data, palettes, photos, footage, museum media). Skip auth-only services
> with no asset payload (e.g. Auth0, weather, finance, etc).
>
> **DO NOT implement these here.** This is a catalog for v1.7+ future slices
> to pick up. Each row notes priority for FAW based on:
>   - **HI** = clean CC0/CC-BY, REST API, predictable shape, broad utility
>   - **MED** = useful for specific scopes (game data lookups, palette/icon gen)
>   - **LO** = OAuth-heavy or niche-only or licensing-encumbered

---

## A. Top 10 picks for FAW v1.7+ slice candidates

These are the highest-leverage adds based on existing FAW recipe / acquisition_router patterns:

| # | API | Category | Auth | License | Useful for | Priority |
|---|---|---|---|---|---|---|
| 1 | **Met Museum API** | Art | No | CC0 (verified open access) | Reference images, period art, painting textures for Roman/historical recipes | **HI** |
| 2 | **Pexels** | Photo + Video | apiKey (free) | Pexels License (free, no attrib required) | Stock photo refs + **free stock video footage** (FAW first video provider) | **HI** |
| 3 | **Pixabay** | Photo + Video | apiKey (free) | Pixabay Simplified (CC0-equivalent) | CC0 photos, vectors, **video** — twin to Pexels for redundancy | **HI** |
| 4 | **Unsplash** | Photo | OAuth (free dev) | Unsplash License (free, mild attribution) | High-quality photo refs; widely-recognized brand | **HI** |
| 5 | **Archive.org** | Open Data | No | Mixed (PD, CC) per item | Public-domain books, scans, audio, video — long-tail asset source | **HI** |
| 6 | **Jamendo** | Music | OAuth | CC-licensed (CC0 / CC-BY tier) | Music tracks for game soundtracks; permissive licenses | **MED** |
| 7 | **Wikimedia Commons / Wikipedia** | Open Data | No | Mixed (PD / CC-BY-SA mostly) | Massive PD/CC media via MediaWiki API | **MED** |
| 8 | **Iconfinder** | Icons | apiKey | Mixed (some CC0, some paid) | UI icon search + filterable CC0 subset | **MED** |
| 9 | **Scryfall** | Game DB | No | CC0 metadata + per-card art use OK | Card-game prototyping (MTG cards as reference textures) | **MED** |
| 10 | **RAWG.io** | Game DB | apiKey (free 20k/mo) | Per-image rights vary | Genre-aware reference (covers/screenshots) for design ideation | **LO** |

**Why these 10:**

Picks 1-5 are **direct fit** for the existing `direct_url` lane shape: REST API → JSON → file URLs → download. Matches the polyhaven/kenney/ambientcg pattern almost exactly. License-clean enough to ship in a recipe without per-asset operator review.

Picks 6-10 are **second-tier**: useful but either auth-heavy (Jamendo OAuth), license-messy per-asset (Wikimedia, Iconfinder, RAWG), or scope-narrow (Scryfall is card-game-specific). Worth wrapping if a real game recipe calls for them.

---

## B. Full filtered shortlist by category (82 APIs)

All entries below survived the filter: free-tier exists, non-paywall search, asset-payload bearing. Use this when picking a slice — the priority column is the FAW-specific recommendation.

### Art & Design (18)

| API | URL | Auth | FAW priority |
|---|---|---|---|
| Art Institute of Chicago | https://api.artic.edu/docs/ | No | **HI** |
| Colormind | http://colormind.io/api-access/ | No | LO |
| ColourLovers | http://www.colourlovers.com/api | No | LO |
| Cooper Hewitt | https://collection.cooperhewitt.org/api | apiKey | MED |
| Dribbble | https://developer.dribbble.com | OAuth | LO |
| EmojiHub | https://github.com/cheatsnake/emojihub | No | LO |
| Europeana | https://pro.europeana.eu/resources/apis/search | apiKey | MED |
| Harvard Art Museums | https://github.com/harvardartmuseums/api-docs | apiKey | MED |
| Icon Horse | https://icon.horse | No | LO |
| Iconfinder | https://developer.iconfinder.com | apiKey | MED |
| Icons8 | https://img.icons8.com/ | No | LO |
| Lordicon | https://lordicon.com/ | No | LO |
| Metropolitan Museum of Art | https://metmuseum.github.io/ | No | **HI** |
| Noun Project | http://api.thenounproject.com/index.html | OAuth | LO |
| PHP-Noise | https://php-noise.com/ | No | LO |
| Pixel Encounter | https://pixelencounter.com/api | No | LO |
| Rijksmuseum | https://data.rijksmuseum.nl/object-metadata/api/ | apiKey | MED |
| xColors | https://x-colors.herokuapp.com/ | No | LO |

### Games & Comics (30)

| API | URL | Auth | FAW priority |
|---|---|---|---|
| AmiiboAPI | https://amiiboapi.com/ | No | LO |
| Animal Crossing NH | http://acnhapi.com/ | No | LO |
| Battle.net | https://develop.battle.net/documentation/guides/getting-started | OAuth | LO |
| Board Game Geek | https://boardgamegeek.com/wiki/page/BGG_XML_API2 | No | LO |
| Comic Vine | https://comicvine.gamespot.com/api/documentation | No | LO |
| Crafatar | https://crafatar.com | No | LO |
| Deck of Cards | http://deckofcardsapi.com/ | No | LO |
| Digimon Information | https://digimon-api.vercel.app/ | No | LO |
| Disney | https://disneyapi.dev | No | LO |
| Dungeons and Dragons | https://www.dnd5eapi.co/docs/ | No | LO |
| Open5e (DnD) | https://open5e.com/ | No | MED |
| FFXIV Collect | https://ffxivcollect.com/ | No | LO |
| XIVAPI | https://xivapi.com/ | No | LO |
| Genshin Impact | https://genshin.dev | No | LO |
| Giant Bomb | https://www.giantbomb.com/api/documentation | apiKey | LO |
| GraphQL Pokemon | https://github.com/favware/graphql-pokemon | No | LO |
| Hyrule Compendium | https://github.com/gadhagod/Hyrule-Compendium-API | No | LO |
| IGDB.com | https://api-docs.igdb.com | apiKey | MED |
| Magic The Gathering | http://magicthegathering.io/ | No | MED |
| Marvel | https://developer.marvel.com | apiKey | LO |
| mod.io | https://docs.mod.io | apiKey | MED |
| Monster Hunter World | https://docs.mhw-db.com/ | No | LO |
| Pokéapi | https://pokeapi.co | No | MED |
| Pokémon TCG | https://pokemontcg.io | No | LO |
| RAWG.io | https://rawg.io/apidocs | apiKey | MED |
| Rick and Morty | https://rickandmortyapi.com | No | LO |
| Scryfall | https://scryfall.com/docs/api | No | MED |
| SuperHeroes | https://superheroapi.com | apiKey | LO |
| TCGdex | https://www.tcgdex.net/docs | No | LO |
| Valorant (unofficial) | https://valorant-api.com | No | LO |
| xkcd | https://xkcd.com/json.html | No | LO |
| Yu-Gi-Oh! | https://db.ygoprodeck.com/api-guide/ | No | LO |

### Music (10)

| API | URL | Auth | FAW priority |
|---|---|---|---|
| Bandcamp | https://bandcamp.com/developer | OAuth | LO |
| Deezer | https://developers.deezer.com/api | OAuth | LO |
| Discogs | https://www.discogs.com/developers/ | OAuth | LO |
| Freesound | https://freesound.org/docs/api/ | apiKey | (already shipped) |
| Genrenator | https://binaryjazz.us/genrenator-api/ | No | LO |
| iTunes Search | https://affiliate.itunes.apple.com/resources/documentation/itunes-store-web-service-search-api/ | No | LO |
| **Jamendo** | https://developer.jamendo.com/v3.0/docs | OAuth | **MED** |
| MusicBrainz | https://musicbrainz.org/doc/Development/XML_Web_Service/Version_2 | No | MED |
| Radio Browser | https://api.radio-browser.info/ | No | LO |
| TheAudioDB | https://www.theaudiodb.com/api_guide.php | apiKey | LO |

### Photography (19)

| API | URL | Auth | FAW priority |
|---|---|---|---|
| APITemplate.io | https://apitemplate.io | apiKey | LO |
| Bruzu | https://docs.bruzu.com | apiKey | LO |
| Flickr | https://www.flickr.com/services/api/ | OAuth | MED |
| Getty Images | http://developers.gettyimages.com/en/ | OAuth | LO |
| Gfycat | https://developers.gfycat.com/api/ | OAuth | LO |
| Giphy | https://developers.giphy.com/docs/ | apiKey | LO |
| Imgur | https://apidocs.imgur.com/ | OAuth | LO |
| Imsea | https://imsea.herokuapp.com/ | No | LO |
| Lorem Picsum | https://picsum.photos/ | No | LO |
| ObjectCut | https://objectcut.com/ | apiKey | LO |
| **Pexels** | https://www.pexels.com/api/ | apiKey | **HI** |
| PhotoRoom | https://www.photoroom.com/api/ | apiKey | LO |
| **Pixabay** | https://pixabay.com/sk/service/about/api/ | apiKey | **HI** |
| Remove.bg | https://www.remove.bg/api | apiKey | LO |
| ReSmush.it | https://resmush.it/api | No | LO |
| Shutterstock | https://api-reference.shutterstock.com/ | OAuth | LO |
| Sirv | https://apidocs.sirv.com/ | apiKey | LO |
| **Unsplash** | https://unsplash.com/developers | OAuth | **HI** |
| Wallhaven | https://wallhaven.cc/help/api | apiKey | LO |

### Video / Open Data (5)

| API | URL | Auth | FAW priority |
|---|---|---|---|
| Pexels (videos endpoint) | https://www.pexels.com/api/ | apiKey | **HI** (FAW would gain its first video provider) |
| Pixabay (videos endpoint) | https://pixabay.com/sk/service/about/api/ | apiKey | **HI** |
| **Archive.org** | https://archive.readme.io/docs | No | **HI** |
| Wikidata | https://www.wikidata.org/w/api.php?action=help | OAuth | MED |
| Wikipedia (MediaWiki API) | https://www.mediawiki.org/wiki/API:Main_page | No | MED |

---

## C. Recommended next slice queue (v1.10+)

If a future session wants to pick up from this catalog, here's the suggested
order, biased toward the existing direct_url lane shape:

1. **v1.10.s26** — Met Museum + Art Institute of Chicago provider (`art_pd` provider name, no-auth, CC0). One slice gets two providers because both APIs use the same shape: GET `/api/v1/objects` → filter `is_public_domain=true` → download `image_url`. Wraps cleanly under `acquisition_router._drive_art_pd`.

2. **v1.10.s27** — Pexels + Pixabay provider (`stock_media` provider name, apiKey). Twin providers for photo + video. Highest-impact slice: gives FAW its first video acquisition path.

3. **v1.10.s28** — Archive.org provider (`archive_org` provider name, no-auth). Long-tail catch-all for public-domain media. License-per-item, but archive.org exposes the license string in metadata so per-asset filter is doable.

4. **v1.10.s29** — Jamendo provider (`jamendo_music` provider name, OAuth). FAW's first OAuth music provider beyond the existing FreeSound apiKey shape. Useful for game soundtracks (CC-licensed music).

5. **v1.10.s30** — Scryfall + IGDB provider (`game_db_ref` provider name). Game-data reference for prototyping: pull MTG card art or videogame cover screenshots as quick mockup material. License-per-image, but both APIs expose terms in response.

Don't implement them here. This catalog is the queue; slices pick them up.

---

## D. APIs we deliberately did NOT pick

For honesty, here's what we found and rejected:

- **Most Games & Comics APIs** — fan-game metadata, fun-to-have but no FAW-relevant payload pattern. Pokemon sprites are cute but a recipe pulling Pokemon sprites is niche; user'd grab them manually.
- **Most TV/movie APIs** (IMDb/TMDB/TVDB) — metadata-only, no usable game-asset payload, license-encumbered.
- **All Auth/Cloud-storage/Crypto/Finance/Weather entries** — outside asset scope.
- **`Dribbble` / `Behance`** — designer portfolios, OAuth-heavy, license-per-shot. Operator can browse manually.
- **`Shutterstock` / `Getty Images`** — paid licenses; free-tier search is preview-only.
- **`Wallhaven`** — anime/wallpaper-heavy, license metadata thin.

---

(End of mine — assetboi 2026-05-11 R1a ride-along)
