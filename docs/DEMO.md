# Controlled CSV demonstration

The small script in examples/csv-lab is intentionally faulty: it reads both files as UTF-8 without stripping the BOM. Running it writes a plain CSV, a BOM CSV, observed.log, environment.txt, steps.txt and a receipt into a new directory. Both contain the same two purchase rows. The observed comparison is12.50 versus KeyError amount. This is actual execution of a constructed bug, not production telemetry or a user interview.

Create an issue with steps.txt as its description and observed.log/environment.txt as attachments. Ask the configured local model to organize it. Compare the two actual outcomes with the log, inspect source links, edit a field, save and confirm. Export with cited excerpts enabled and full sources disabled. Reopen history to see that the original AI version still exists.

The recording is assembled from actual Egolite UI frames with English captions and cuts between actions. It contains a real local-model request and no generated interface. No audio, user study or participant reflection is implied. Publication is a separate step.
