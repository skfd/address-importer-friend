# Licence review + government-contact TODO (operator actions)

State as of the 2026-08-16 licence review pass over every non-green dataset in
`ontario-address-changes/datasets/` (amended 2026-10-09: Oakville's licence
approved by the LWG). Method: fetch the licence page where one
is published; for ArcGIS-hosted layers, read `licenseInfo` off the portal item
(service JSON → `serviceItemId` → item metadata). OSMF process reference:
<https://osmfoundation.org/wiki/OGL_Canada_and_local_variants>; waiver/permission
templates: <https://osmfoundation.org/wiki/Licence/Waiver_and_Permission_Templates>.

Draft LWG email (drafted for six OGL clones, unsent):
<https://gist.github.com/skfd/043eded6a26b279b7cf75aa3927b14da>
— it still lists Oakville; take Oakville out before sending (see §A).

Every outbound contact below is an **operator action** — a human writes to a
government office; none of it is automatable or delegable to a probe.

## A. Desk work only — no contact required

- [x] **oakville** — approved without our email: the OSMF variants page lists
      "Town of Oakville Open Data Licence (PDF)" as compatible (LWG minutes
      2026-09-14; page edit "Added Oakville", 2026-09-14). The Contributors
      page already has an Oakville entry. Verified 2026-10-09. The tracker's
      `oakville.toml` tier flip is the tracker's job.
- [ ] **Send the LWG email** (the gist) covering brantford, dufferin, huron,
      kitchener, **sarnia** — five now; remove Oakville from the gist first —
      after a human read of the two licences verified only from page
      summaries (brantford, kitchener; dufferin + huron + sarnia are
      verbatim-verified). Re-checked 2026-10-09: none of the five, nor peel,
      is on the OSMF variants page yet.
- [ ] **brant** — item `licenseInfo` is literally **"CC0"**
      (item cfcb7930439e42b386410b716869d170, owner OpenData_Brant). CC0 is
      ODbL-compatible outright. Optionally confirm the marking is intentional
      with the county, then re-tier `brant.toml` unknown-review → green.
- [ ] **peel-region** — a real licence exists: "Open Data Licence for The
      Regional Municipality of Peel (Version 1.0)", **based on the UK OGL**,
      adapted with permission of the UK National Archives. Full text is at
      <https://data.peelregion.ca/pages/license> but the page is JS-rendered —
      grab the text in a browser, diff against UK OGL 3.0 / OGL-Canada 2.0,
      then add Peel to the LWG email. **Highest-value item on this list:**
      Peel is the gateway to Mississauga, the designated first
      regional-dataset city.
- [ ] After LWG replies: add Contributors-page entries and flip
      `osm_compatible` tiers in the tracker datasets. (Oakville's
      Contributors entry already exists.)
- [ ] **Tracker tiers the OSMF page does not back** (found 2026-10-09):
      the tracker marks barrie, greater-sudbury and durham (Oshawa licence)
      `green-lwg` and lambton `green-ogl`, but none of the four appears on
      the OSMF variants page. niagara-falls matches only via "Open
      Government License 2.0 (Niagara Region)" (LWG 2024-06-10). Barrie is
      an onboarding import target, so it matters first. Find the evidence
      behind each tier (LWG minutes, Contributors entry, or a licence that is
      verbatim OGL-Ontario/Canada) or get the tracker to re-tier — the tiers
      live in the tracker repo and are not changed here.

## B. Contact: CC-BY waiver ask

- [ ] **brampton** — confirmed CC BY 4.0 on the GeoHub. CC BY needs the
      standard OSMF waiver (attribution-mechanics + DRM clauses). Write to
      **open@brampton.ca** using the OSMF waiver template. Tier stays
      orange-ccby-waiver until signed.

## C. Contact: no published licence — ask them to state one

Nothing to review: the item metadata is empty and no licence page was found.
Ask each to either point at their licence text or grant OSM-specific
permission (template above). Sorted by known contact first.

- [ ] **bruce** — toml says "BGDISC Open Data Licence" but BGDiSC is a
      data-sharing collaborative, not a licence; hub pages are JS shells with
      no terms found. Contact **GIS@BruceCounty.on.ca**.
- [ ] **lennox-addington** — item licenseInfo names an "Open Data Policy";
      the portal launch announcement claims "no restrictions on use,
      distribution, or modification" but publishes no licence text. Ask
      **gisservices@lennox-addington.on.ca** to confirm in writing / publish.
- [ ] **hastings** — tracker's "Open Government Licence - The Corporation of
      the County of Hastings" is aspirational: item licenseInfo reads
      "General use. Open Data." and no licence document exists in the org or
      hub. Contact the county GIS office.
- [ ] **kawartha-lakes** — item carries a *disclaimer* ("for reference
      only", no warranty), not a grant. No redistribution rights conveyed as
      written. Contact the city GIS office.
- [ ] **chatham-kent** — empty licenseInfo. Contact municipal GIS.
- [ ] **elgin** — county-hosted server, no metadata. Contact county GIS.
- [ ] **frontenac** — empty licenseInfo (owner FrontenacGIS). Contact county.
- [ ] **leeds-grenville** — only an attribution line, no licence. Contact
      counties GIS.
- [ ] **milton** — city-hosted server, no metadata. Contact town GIS.
- [ ] **muskoka** — proxied service, no metadata. Contact district GIS.
- [ ] **peterborough-county** — empty licenseInfo. Contact county GIS.
- [ ] **renfrew** — empty licenseInfo. Contact county GIS.
- [ ] **wellington** — empty licenseInfo (owner WellingtonPlanning). Contact
      county GIS. (Bbox note: Guelph sits wholly inside Wellington —
      clipping applies regardless of licence.)

## D. Contact: published terms are restrictive — permission ask, uphill

- [ ] **sdg** — item licenseInfo is explicit copyright terms: "No part of
      the information herein may be sold, copied, distributed, or transmitted
      in any form without the prior written consent of the County." An OSM
      permission grant is the only path; effectively red today.
- [ ] **burlington** — red-review, "City of Burlington Terms of Use".
      Re-pull the terms, then permission ask.
- [ ] **london** — red-review, "City of London Terms of Use". Same.
- [ ] **windsor** — red-review, "City of Windsor Terms of Use" (mappmycity.ca).
      Same.

## Suggested ask (C and D)

> We'd like to use your published civic address data to improve
> OpenStreetMap, the free collaborative world map. OSM's licence (ODbL)
> requires that source data be under compatible open terms; many Ontario
> municipalities publish under an Open Government Licence modelled on
> OGL-Canada 2.0 (e.g. Toronto, Hamilton, Ottawa). Could you tell us which
> licence applies to the address layer — or, if none is published, would the
> county consider adopting one, or granting the permission in the attached
> OSMF template?

Findings memo with per-city evidence: memory store
`ogl_variant_review_2026_08_16.md` (session-local), and the gist above.
