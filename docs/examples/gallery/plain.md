A note on why Halyard keeps carrier timestamps exactly as the carrier sent them.

Every carrier reports a scan time in its own timezone, with its own idea of precision. Carrier A
sends UTC to the second. Carrier B sends local time with no offset at all, which is only
interpretable if you already know which depot handled the parcel.

The tempting move is to normalise on the way in — parse everything, convert to UTC, store one clean
column. We do not do that, and the reason is worth writing down because it keeps coming up.

Normalising on ingest throws away the only evidence of what the carrier actually claimed. When a
customer disputes a delivery time, the question is never "what does our database say". It is "what
did the carrier tell you, and when". A converted timestamp cannot answer that, and a conversion bug
is undetectable after the fact because the original is gone.

So we store the carrier's string verbatim, alongside our best interpretation and the rule we used
to interpret it. Three columns instead of one. Queries use the interpretation. Disputes use the
verbatim value. When we later discover that carrier B's depot mapping was wrong for six weeks in
2024, we can recompute every affected interpretation, because the input still exists.

This costs storage and it costs a small amount of query complexity. It has already paid for itself
once.
