# Licence review + government-contact TODO (operator actions)

State as of the 2026-08-16 licence review pass over every non-green dataset in
`ontario-address-changes/datasets/` (amended 2026-10-09: Oakville's licence
approved by the LWG; amended 2026-10-11: the LWG email was sent). Method:
fetch the licence page where one is published; for ArcGIS-hosted layers, read
`licenseInfo` off the portal item (service JSON → `serviceItemId` → item
metadata). OSMF process reference:
<https://osmfoundation.org/wiki/OGL_Canada_and_local_variants>; waiver/permission
templates: <https://osmfoundation.org/wiki/Licence/Waiver_and_Permission_Templates>.

LWG email covering six OGL clones — sent (date not recorded), no reply as of
2026-10-11. Draft:
<https://gist.github.com/skfd/043eded6a26b279b7cf75aa3927b14da>

Every outbound contact below is an **operator action** — a human writes to a
government office; none of it is automatable or delegable to a probe.

## A. Desk work only — no contact required

- [x] **oakville** — the OSMF variants page lists "Town of Oakville Open
      Data Licence (PDF)" as compatible (LWG minutes 2026-09-14; page edit
      "Added Oakville", 2026-09-14). The Contributors entry was added
      2026-08-31 by `TronnaLegacy`, following the self-service procedure on
      the OSMF variants page. Which message prompted the listing is not
      known. Verified 2026-10-09. The tracker's
      `oakville.toml` tier flip is the tracker's job.
- [x] **Send the LWG email** (the gist) covering oakville, brantford,
      dufferin, huron, kitchener, **sarnia** — sent (date not recorded); no
      reply as of 2026-10-11. Re-checked 2026-10-09: the other five, and peel,
      are still not on the OSMF variants page.
- [ ] **Next: the self-service route for the five** (and other Ontario
      licences): diff each against the Ottawa Open Data Licence 2.0 per the
      OSMF variants page; where the only differences are locality name, legal
      venue, PII or "records" definitions, add a Contributors entry and email
      legal-questions@osmfoundation.org. Follow up with legal-questions@ for
      any that are not a pure variant of that kind. Diffs in progress in
      `ontario-osm-data-sources/licences/`. Brantford and kitchener were
      verified only from page summaries — read their full text first.
- [ ] **brant** — item `licenseInfo` is literally **"CC0"**
      (item cfcb7930439e42b386410b716869d170, owner OpenData_Brant). CC0 is
      ODbL-compatible outright. Optionally confirm the marking is intentional
      with the county, then re-tier `brant.toml` unknown-review → green.
- [ ] **peel-region** — a real licence exists: "Open Data Licence for The
      Regional Municipality of Peel (Version 1.0)", **based on the UK OGL**,
      adapted with permission of the UK National Archives. Full text is at
      <https://data.peelregion.ca/pages/license> but the page is JS-rendered —
      grab the text in a browser, diff against UK OGL 3.0 / OGL-Canada 2.0,
      then follow up with legal-questions@osmfoundation.org (a UK-OGL base
      is not a pure locality variant). **Highest-value item on this list:**
      Peel is the gateway to Mississauga, the designated first
      regional-dataset city.
- [ ] As each licence clears: add Contributors-page entries and flip
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

## E. Tracked from 2026-10-16 onward, gated off the site — asks drafted 2026-10-23

The ontario-address-changes tracker added these with `publish_reports = false` (licence
decides publishing, never tracking). Each ask below lifts a gate if it succeeds. Two
questions per place: may we publish change reports derived from the layer (the tracker),
and under what licence (OSM). Use the suggested ask below; add the tracker sentence:
"We also publish a daily list of added/retired/changed addresses derived from the layer
- is that permitted?" Contacts seen on official pages 2026-10-23 (evidence URL in brackets).

No licence published anywhere (ask them to state one):
- [ ] **caledon** - info@caledon.ca (no GIS address) [caledon.ca/contact]
- [ ] **dryden** - generalinquiries@dryden.ca (maps page says contact the City) [dryden.ca/build-invest/maps]
- [ ] **oshawa** - service@oshawa.ca, the open-data page's contact. Also ask whether the
      "Open Data Licence Agreement ... for reference use only" the registry quoted
      covers Parcels_AddPts. [oshawa.ca/city-hall/city-records/open-data]
- [ ] **vaughan + vaughan-ng911** (one ask) - service@vaughan.ca (seen only in a search
      snippet; vaughan.ca returned 403 to a direct fetch) [vaughan.ca/contact-us]
- [ ] **grey + grey-assigned-addresses + blue-mountains** (one ask; all three are layers
      on gis.grey.ca) - web form only: form.foreaction.cloud/submit/grey-county [grey.ca/contact-us]
- [ ] **gorham-ware + oliver-paipoonge** (one ask) - published by Lakehead Region
      Conservation Authority on NVCA's server: info@lakeheadca.com [lakeheadca.com/about-us].
      Who owns the data is unclear; Oliver Paipoonge also lists planning@oliverpaipoonge.on.ca.
- [ ] **leamington** - clerks@leamington.ca (no GIS or general address) [leamington.ca news
      post]. The layer sits in the County of Essex AGOL org but is not on the County hub, so
      the County OGL that covers tecumseh may not reach it - CC the County form below.

Restrictive terms published (permission ask, uphill):
- [ ] **oxford** - gis@oxfordcounty.ca (confirmed; also addressing@oxfordcounty.ca). The
      data-requests page grants a "limited licence": no posting on an external website, no
      commercial use. [oxfordcounty.ca/services-for-you/data-requests]
- [ ] **north-bay** - customerservice@northbay.ca (northbay.ca/legal forbids copying onto
      other websites without written agreement) [northbay.ca/contact-us]
- [ ] **haliburton** - gis@haliburtoncounty.ca (view-and-print-a-single-copy terms plus an
      anti-scraping clause - the hardest terms in the catalogue) [haliburtoncounty.ca/planning-and-maps/maps]
- [ ] **sault-ste-marie** - info@cityssm.on.ca; the service is hosted by the Sault Ste. Marie
      Innovation Centre (enterprise.ssmic.com), no contact found for them. SooMaps terms are
      non-commercial only. [saultstemarie.ca/contact]
- [ ] **peterborough (City)** - gis@peterborough.ca, named on the open-data page. The Terms
      allow copying only UNMODIFIED datasets; ask whether derived change reports count.
      [peterborough.ca/en/city-hall/open-data.aspx]

Publishing already; confirmation asks:
- [ ] **ajax** - GISServices@ajax.ca. **New wrinkle:** the opendata.ajax.ca site settings
      list the licence as "CC-BY-SA", while the tracker read the Town of Ajax Open Data
      Licence v1.0 (OGL clone) off the hub's site-wide text. Ask which applies to Civic
      Addresses item e48315e9; CC-BY-SA would not be ODbL-compatible without a waiver.
      [arcgis.com/sharing/rest/content/items/5a328e1aa7ac469c8dcc16dd12f298bc/data?f=json]
- [ ] **tecumseh** - the County is the licensor: County of Essex GIS Open Data Feedback form
      eforms.countyofessex.ca/GIS/Open-Data-Feedback (or coeinfo@countyofessex.ca); Town is
      info@tecumseh.ca. Ask whether the County OGL may license the Town's points.
      [countyofessex.ca/discover-the-county/open-data]

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
