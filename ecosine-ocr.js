/* ==========================================================================
   ECOSINE — OCR helper (JXA)

   Reads text out of a scanned image using macOS's built-in Vision framework.
   No third-party dependency: Vision ships with the OS, and reaching it through
   JavaScript for Automation keeps the whole project dependency-free.

   Usage:  osascript -l JavaScript ecosine-ocr.js <image-path>
   Prints the recognised text, one observation per line.
   ========================================================================== */
ObjC.import('Foundation');
ObjC.import('Vision');
ObjC.import('AppKit');

function run(argv) {
  if (!argv.length) return 'ERR: no image path given';

  const url = $.NSURL.fileURLWithPath($(argv[0]));
  const img = $.NSImage.alloc.initWithContentsOfURL(url);
  if (!img || img.js === undefined) return 'ERR: could not load image';

  const bmp = $.NSBitmapImageRep.imageRepWithData(img.TIFFRepresentation);
  if (!bmp || bmp.js === undefined) return 'ERR: could not decode image';

  const handler = $.VNImageRequestHandler.alloc.initWithCGImageOptions(bmp.CGImage, $());
  const req = $.VNRecognizeTextRequest.alloc.init;
  req.recognitionLevel = 1;              // 1 = accurate (0 = fast)
  req.usesLanguageCorrection = true;
  // UAE paperwork is bilingual; ask for both so Arabic lines aren't dropped.
  try { req.recognitionLanguages = $(['en-US', 'ar-SA']); } catch (e) { /* older macOS */ }

  const err = $();
  handler.performRequestsError($([req]), err);

  const results = req.results;
  if (!results || results.js === undefined) return '';

  const out = [];
  for (let i = 0; i < results.count; i++) {
    const cand = results.objectAtIndex(i).topCandidates(1);
    if (cand && cand.count > 0) out.push(ObjC.unwrap(cand.objectAtIndex(0).string));
  }
  return out.join('\n');
}
