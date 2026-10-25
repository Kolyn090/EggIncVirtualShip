# Egg, Inc. artwork provenance and rights

44 of the PNG files in this directory are unmodified, full-color copies from:

- Repository: https://github.com/fanaticscripter/EggIncAssets
- Revision: `075805d987ae55d74579abff3f75f9b28e84d5fc`
- Source directory: `64/egginc/`
- Original artwork: the Egg, Inc. game creators/rightsholders.
- Asset extraction/size variants: fanaticscripter/EggIncAssets contributors.

Checked October 25, 2026: the full repository tree contains no LICENSE,
COPYING, or NOTICE file. Its only README, `orig/egginc/README.md`, says:

> Extracted from Android apk, `assets/textures-etc1png-med`.
>
> Latest version: v1.20.0.

The repository does not state a redistribution license or attribution terms.
Public availability is not an open-source license or a grant from the artwork
owner. This notice records provenance and credit; it does not grant rights,
claim ownership, or relicense the artwork under any project/software license.
Egg, Inc. artwork and marks remain with their respective rights holders. This
is an unofficial fan tool and is not endorsed by the Egg, Inc. game creators.

`manifest.json` records exact source filenames and SHA-256 checksums. The build
verifies original bytes before embedding them as data URLs for offline use in
the sandboxed dashboard. Images are only scaled with CSS to 32–34px; no tint,
recoloring, completion-state filter, or pixel transformation is applied.

All currently supported target profiles use the highest numbered artwork in
their material family: T4 artifacts/stones and T3 geodes, meteorites and solar
titanium. Stone-fragment target profiles deliberately share their family's
highest-tier stone artwork. Tier aliases change presentation only.

The upstream source has ten ship-family icons, no ship-level variants, and no
Henliner icon at this revision. `chicken_1` and `chicken_9` are different ship
families, not levels.

The additional `afx_ship_atreggies.png` is the user-provided 64×64 Henliner
artwork from this project's `image/afx_ship_atreggies.png`, not from the pinned
EggIncAssets revision. It is copied byte-for-byte by the PWA build and its local
source path and checksum are recorded separately in `manifest.json`. Existing
artwork rights remain unchanged. Both `henliner` and `atreggies` identifiers use
this artwork. Unknown ships/targets and untargeted missions retain readable
text; failed image loads also fall back to text.
