# Day 1 Progress Report

Worked only for half a day. Processed 81 out of 1297 tiles.

Suburbs -- super-easy -- legacy housing zones like duplexes is almost automatic. 

Suburbs -- caveat --  addresses that were surveyed without street name -- must carefully review, and later merge with building geometries.

Downtown -- what is not that easy -- every downtown tile had minor mapping errors like house addresses confused between two buildings. Buildings having correct numbers, but wrong street names. Each case requires looking at Mapillary, survey notes, item histories.

Fun bugs in Source Data itself -- for example "10 Roanoke Rd" - "8 Roanoke Rd" pair confused; 98 Redpath Ave and 106 Redpath Ave pair confused. Any idea where to report it?

Typical funny issue -- some one deleted address interpolation *line*, but not they end-points that become free-floating addresses. This again leaves me no choice but to whip up iD and move existing addresses to exact position.


Overall, it feels good. Please review the [log of the import](https://www.openstreetmap.org/user/skfd%20imports/history).

I want to also record the video of a process, just for fun, tomorrow.


# Day 2 and 3 Progress Report

Tiles processed: 81/1297 → 246/1297.

Another quirk -- alternative names -- Sunny Slope had "alt_name=Sunnyslope Avenue;Sunny Slope Avenue" but my parser only expected, so it created dupes. My bad, fixed manually.

Off by one errors -- surveyed addresses were shifted by one house. Tool highlighted it as "Found match, but it's too far from where I would put it" -- incredibly easy to miss, requires careful manual fix -- shifting the position of existing addresses, making sure tool creates missed addresses and skips already existing ones. [Example changelog](https://www.openstreetmap.org/changeset/182757497).

Here is a [slice of life video](https://www.youtube.com/watch?v=YbMDQD2bH7k) of the import process. Forgive me for bad sound, I live next to highway (Kingsway).


# Day 4 and 5 Progress Report

Tiles processed: 246/1297 → 403/1297.

Observation -- trip malls have so many addresses right next to each other. And this is a fragile data -- one people will add a restaurant to pure address node, and later another person will delete the point when it's closed.

Funniest thing happened -- my own on-the-ground survey of new development gave me stress when reviewing city data. City data shows some real building numbers, but on the ground it's all cloned building number with different block letters. See [Clonmore Urban Towns](https://www.openstreetmap.org/way/1417969244) 

Incredibly annoying -- same street named [Linsmore Crescent](https://www.openstreetmap.org/way/28408669#map=18/43.686541/-79.331717&layers=N) vs [Linnsmore Crescent](https://www.openstreetmap.org/way/311032240#map=19/43.683658/-79.330452&layers=N). Absolutely not a Crescent, as a salt on the map gore wound.

Curious -- in 2014 user came in and [marked their old address](https://www.openstreetmap.org/changeset/22371527) on OSM. They have a lovely web 1.0 [personal site](https://darcy.druid.net/) with incredible domain name. So much personal history is there somewhere in OSM logs, if you think about it. 


Mystical area I would call ["Address Graveyard"](https://www.openstreetmap.org/edit#map=20/43.7860832/-79.3516372). Probably need to move all these unto nearby mall...

Incredibly stressful fixing of address drift/off by one errors in Woodbine. Woodbine Avenue, Coleridge Avenue, King Edward Avenue -- all need to be re-surveyed.

What I need to do as a side-quest -- make a layer for JOSM that will show city address data, and street geometries (if we are allowed to use too).

Happy a great V***a Day!


# Day 6 Progress Report

Tiles processed: 403/1297 → 461/1297.

Concentrated on building numbers drift/off-by-one errors. Re-reviewed already processed tile to double  check if I missed something.


# Day 7 Progress Report

Tiles processed: 461/1297 → 651/1297. Half-way done!

Toronto is full of pagan superstitious -- many building number 13 are skipped, so we often get [address drift errors](https://www.openstreetmap.org/changeset/182998489).

One of the only places where I went in and removed all existing addresses and added my own -- too many mis-aligned ones and untouched for 8 years. Mystical land of [The Fernways](https://www.openstreetmap.org/way/32942937).


# Day 8 Progress Report

Tiles processed: 651/1297 → 760/1297.

To improve my moral I added a button to go to easiest tile, instead of the closest one so I can work on something easy for a while.

Awekward moment for future mappers -- some building had numbers as if if it's a detached cottage, but it's actually a duplex so importer adds a point with different number. So the mappers would have to manually extract address from building polygon into point, because importer skipped doing -- it exists, does it not? This comes from our pormise to never touch OSM existing data with importer and only add (or NOT add) nodes.

45A Alvin Ave -- another city point error, where OSM has it correct.



# Day 9 Progress Report

Tiles processed: 760/1297 → 900/1297.

*BIG NEWS*: Made a [addresses layer](https://skfd.github.io/toronto-addresses-layer/) you can use in JOSM or iD to reference City Data.

Many main street sections had [12 year old address errors](https://www.openstreetmap.org/changeset/183133996#map=19/43.665807/-79.469904&layers=N), which I fix manually. I feel like this area would need much more manual work and mapper attention, I am trying my best but it feels like an out of scope terrirotry for semi-automated import. Please use new address layer to double check everything if you like. Cheers!



# Day 10 Progress Report

Tiles processed: 900/1297 → 1026/1297.

Detail -- should have been setting [addr:source](https://taginfo.openstreetmap.org/keys/addr%3Asource), instead of generic `source` tag. This would have tied it to specific data type and survived merges with buildings. I think I will bulk-replace it after I'm done.

Still getting psychic damage from how mis-aligned buildings in East End are, but resisting getting bogged down in telemapping instead of importing.

Another funny city data bug -- "90 Heath Street West" and "80 Heath Street West" are confused. City seem to be confused by same looking aparment buildings.

`source=CanVec 6.0 - NRCan` individual nodes slowing me down because I need to delete them one by one, as very inacurate. These nodes are leftover pieces of street Interpolations. Someone deleted interpolation but left the terminal nodes at street corners which light up as legit addresses. Sad!



# Day 11 and 12 Progress Report

Tiles processed: 1026/1297 → 1148/1297.

Message to community -- there is a lot of telemapping to do in suburbs (like Long Branch and all of North York)! Please review the building shapes people keep rebuilding their tiny cottages into slightly bigger cottages.

I wanted to mention that addresses like "645A Bloor Street West" are imported as: 

```
addr:housenumber=645A
addr:street=Bloor Street West
```

NOT as:

```
addr:housenumber=645
addr:street=Bloor Street West
addr:unit=A
```

Funny -- [Ontario Legislative Building](Ontario Legislative Building) south entrance address -- *Queen's Park* is a vernacular name used government itself, but official address is *Queen's Park Crescent*. Google maps are handling that well, I wander if Nominatim does it well too.

Another City mistake corrected by someone with local knowledge -- [1-6 Avonhill Court](https://www.openstreetmap.org/#map=19/43.785139/-79.430443&layers=N), a tiny cull de sac.

Another city mistake, typical two-apartment-buildings-with-switched-addresses -- [16 and 24 The Links Road](https://www.openstreetmap.org/#map=18/43.751215/-79.402142&layers=N).


# Day 13 Progress Report, Final Day

Tiles processed: 1148/1297 → 1297/1297.

Another city data mistake -- [10-80 Laidlaw Street](https://www.openstreetmap.org/#map=19/43.640511/-79.426477&layers=N).

Another city data mistake -- [33 Wascana Ave](https://www.openstreetmap.org/#map=19/43.658000/-79.357408&layers=N) is mis-placed.

Another city data mistake -- [1110 Don Mills Rd and 980 Lawrence Ave E](https://www.openstreetmap.org/#map=19/43.737466/-79.344108&layers=N) are confused.

I will start new thread to discuss the Interpolation Clean Up mapping party we want to have in a few day.

And now [i'm going off the map](https://youtu.be/FH_CUSu7M1Q?si=Co734WkyFaPRVU1S). Cheers!

