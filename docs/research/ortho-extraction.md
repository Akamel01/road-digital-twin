# Classical extraction of markings, crosswalks and curbs from a 5 cm orthoimage plus LiDAR height raster

Research note for issue #260 (part of #257, blocks #261). Research only: no code or contract change.

Input assumed: true-colour orthoimage, 5 cm GSD, averaged over several drives, with unobserved holes; LiDAR ground/height raster; Boston Seaport, US paint (white, yellow). Targets: P95 <= 0.15 m markings, <= 0.20 m crosswalks, <= 0.30 m curbs. Current LiDAR-intensity clustering: P95 ~0.8 m.

Evidence labels: **[read]** = I opened the source this session; **[snippet]** = seen only in a search result or abstract; **[memory]** = classic reference cited from background knowledge, not re-opened (check before quoting).

## Summary

1. No primary source reports P95 positional error for pixel-level classical extraction from a 5 cm orthoimage. Published numbers are detection scores (completeness, correctness, F1), so the P95 targets are unproven and must be measured on our own hand-labelled set.
2. The closest classical pipeline is the Waterloo MLS line (Guan 2014; Ma 2019): road surface by curb height step, then a 4-5 cm georeferenced intensity image, local/multi-threshold segmentation, morphological closing, geometric classification. Our orthoimage plays the role of their intensity image. They report completeness 0.96, correctness 0.83 (Guan, [read]) and recall 90.8 / precision 92.9 / F1 91.9 % (Ma, [read]). Neither reports P95 distance.
3. Curbs from a height step is well established: a 5-30 cm elevation jump plus a slope test (Guan: Gmin 0.08, Gmax 0.30 m; Ma: Hmin 5, Hmax 30 cm, slope >= 60 deg) [read]. Curbs are hard to see in aerial imagery (DLR, [read]), so height must lead and the image only refines position (design inference).
4. At 5 cm GSD the 0.15 m target is 3 pixels. It is plausible only if (a) ortho-to-LiDAR registration is better than ~5 cm and (b) multi-drive averaging has not blurred edges. Both are unmeasured and are the top risks. Reported ortho-to-LiDAR geo-registration accuracy is 15-75 cm [snippet, arXiv 1904.09047], which alone would break the target.
5. Recommended baseline: ROI from height raster, white top-hat + Lab-b* yellow, hysteresis threshold, component geometry against MUTCD widths, RANSAC/Huber line fits with half-max sub-pixel edges, crosswalk grouping by parallel pitch, Douglas-Peucker vectorisation. Details below.

## 1. Thresholding and colour spaces

- Global Otsu works when the histogram is bimodal; on road scenes with shadows, sealed cracks and uneven wear it is not enough. Billah and Rahman (2019) used IDW raster + Otsu for MLS intensity [snippet]. Otsu 1979 [memory].
- Local/adaptive thresholds handle uneven brightness. Li et al. (2016) partition the road and threshold per partition because "non-uniform intensity" defeats global thresholds [read, scipedia copy]. Yao et al. (2018) use adaptive thresholding on an integral image, no intensity calibration, F-score 0.83 for extraction, 0.9 average classification rate [read, abstract]. Guan 2014 slices thresholds by point density [read]. OpenCV offers `cv2.adaptiveThreshold` (mean/Gaussian) and scikit-image `threshold_sauvola`/`threshold_local`; Sauvola & Pietikainen 2000 [memory].
- Image-specific (our case, design inference): white paint = bright and low-chroma. Use a white top-hat (`cv2.morphologyEx(..., MORPH_TOPHAT)` or `skimage.morphology.white_tophat`) on L* (Lab) or min(R,G,B) with a structuring element larger than the widest stripe (~0.6 m = 12 px). A top-hat removes slowly varying shade, which is what shadows and sun/shade pavement look like at this scale. Yellow = high Lab b* (or HSV hue ~20-35 deg with saturation floor); threshold b* locally. Lab separates lightness from chroma better than RGB; HSV hue is unstable at low saturation.
- Hysteresis (`skimage.filters.apply_hysteresis_threshold`): high threshold seeds, low threshold extends. Helps worn paint stay connected without admitting noise (design inference).

## 2. Morphology and skeletons

- Closing with a linear structuring element refines candidates and raises completeness (Guan: best kernel length 3 at 4 cm; completeness stable above 7, correctness falls with kernel size) [read]. Small-object removal in the binary image (Yao) [read].
- Skeletonise for centrelines: `skimage.morphology.skeletonize` (Zhang-Suen 1984 [memory]). Skeletons shift at ends and spur on rough edges; prune short spurs. For positional accuracy of paint edges, fit the edges, not the skeleton (see 3).
- Resolution: Guan found best results at 4-5 cm raster, slowly worse beyond 5 cm [read]. 5 cm GSD is at the sweet spot but no finer.

## 3. Line fitting, RANSAC, sub-pixel edges

- Hough was used for MLS markings (Takahashi 2016 [snippet]); Guan notes prior Hough use [read]. `cv2.HoughLinesP` finds straight segments but gives poorly localised edges; use it only to seed.
- RANSAC (Fischler & Bolles 1981 [memory]; `skimage.measure.ransac`) or Huber `cv2.fitLine` on boundary points of one component gives a line to well under a pixel when the edge is straight and long. Curved lane lines: cubic spline fit, as Ma 2019 does for curved markings, noting zebra crossings are removed by spline-fit residual there [read].
- Edge localisation bias: thresholding at a fixed level moves the edge with paint brightness. Use the half-maximum between local paint and pavement level, or a zero-crossing of the second derivative; Steger 1998 unbiased line detector gives sub-pixel ridge positions [memory].
- Marking width priors are tight: MUTCD crosswalk lines 6-24 in (0.15-0.61 m), stop lines should be 12-24 in (0.30-0.61 m) [snippet, 2009 edition Sections 3B.18 and 3B.16; 11th edition not checked]. A normal lane line is 4-6 in (0.10-0.15 m) = 2-3 px at 5 cm, so lane-line P95 <= 0.15 m is a sub-pixel-fit problem, not a segmentation problem.

## 4. Crosswalks and stop lines

- Li et al. (2016): adaptive threshold per partition, dispersion-degree filter, stripes recognised by rectangularity (regions with an e value > 0.99 are candidates) and fixed length/width, PCA for orientation; total recognition rate 90.91 % on three Optech Lynx datasets [read, scipedia copy]. Positional accuracy not reported in what I read.
- Riveiro et al. (2015, cited in Li) use geometric perpendicularity to separate rectangular markings [snippet].
- Classical aerial-image crosswalk detection is thin in the literature; found work is template matching + SURF, SVM on HOG/LBP, and a patent on directional first-derivative scans [snippet]; modern results are deep learning. No classical aerial accuracy figure found.
- Baseline grouping (design inference): per component `cv2.minAreaRect`; keep rectangles with width in the MUTCD range and aspect > 3; group by orientation (within ~5 deg) and regular spacing along the perpendicular; require >= 3 bars; fit crosswalk extent as the envelope of the bar rectangles. Stop line: single long rectangle, width 0.30-0.61 m, perpendicular to lane direction, within a few metres of the crosswalk.

## 5. Curbs: height step + image edge

- Height step is the established signal: elevation jump and slope-difference thresholds per profile, curb height 10-25 cm in most countries, search window 5-30 cm [Guan, Ma; read]. They fit curb points with B-spline to give smooth road edges [read].
- Failure: worn, settled or ramped curbs break the test (Ma, Dataset IV) [read]. Ramps and driveways have no step: expect gaps.
- Aerial image curb detection is weak: DLR notes curbs are "hardly visible" from airborne imagery, even to annotators [read]; their method is deep learning, not classical, and not our baseline.
- Position precision depends on the height raster's cell size. If it is coarser than 5 cm, the step edge is quantised to a cell. Design inference: locate the step to the cell, then snap to the nearest image edge (Canny, Canny 1986 [memory]) within ~0.3 m, where the kerb face / gutter line shows as a luminance edge. This is untested; verify against hand-labelled kerbs before adopting.
- Curb target 0.30 m is looser than paint targets, so height-only may already pass; image snapping is an option, not a requirement.

## 6. Vectorisation and regularisation

- Douglas-Peucker simplification (`skimage.measure.approximate_polygon`, `cv2.approxPolyDP`; Douglas & Peucker 1973 [memory]) with tolerance 2-3 cm (< 1 px) to avoid biasing positions.
- Regularise only where geometry is known: crosswalk bars to rectangles with common orientation; stop line perpendicular to lane axis; lane lines to splines or clothoid-like polylines. Do not snap if it moves points > the target error.
- Join gaps in dashed or worn lines using direction-aware linking along the fitted curve.

## 7. Failure modes (and what the sources show)

| Failure | Evidence | Mitigation |
|---|---|---|
| Shadows, uneven illumination | Li 2016: poor lighting, tree shadow [read]; global thresholds fail | top-hat / local thresholds, work in Lab L* |
| Worn paint, gaps | Ma 2019: wear breaks curve fitting [read] | hysteresis, gap linking, spline fitting |
| Occlusion (cars, pedestrians) | Ma 2019: paint under vehicles missed [read] | mask holes as nodata, never as negatives; accept incompleteness |
| Averaged-drive blur / ghosting | not in sources; our data specific | measure edge sharpness; fall back to per-drive imagery if blurred |
| Ortho-LiDAR misregistration | 15-75 cm reported for LiDAR-ortho geo-registration [snippet] | estimate and remove offset before fusing (ECC / phase correlation on gradients, check on curbs) |
| Wet pavement, glare, tar seams, crack sealant | typical; not quantified in sources read | colour/geometry filters, width priors |
| Curb ramps, worn curbs | Ma 2019 Dataset IV [read] | accept gaps, bridge by spline |

## 8. Recommended baseline pipeline

All stack parts exist in numpy, scipy, scikit-image, OpenCV.

1. **Register.** Estimate and remove ortho-vs-LiDAR offset (`cv2.findTransformECC` or `skimage.registration.phase_cross_correlation` on gradient images), check residual on curb lines. Gate: residual <= 5 cm P95, else stop and fix registration first.
2. **Road ROI + masks.** From the height raster: ground, curb step (5-30 cm, slope test), road surface between curbs. Add the nodata mask from observation holes.
3. **Paint candidates.** White: top-hat (r ~12 px) on L*, then local threshold + hysteresis. Yellow: local threshold on b*. Within ROI, outside nodata.
4. **Clean.** Remove small components, linear closing (length ~3-7 px), opening to drop thin speckle.
5. **Classify** by `minAreaRect` width/length against MUTCD ranges; group crosswalk bars by orientation and pitch; identify stop lines; remaining long components are lane lines.
6. **Localise.** Half-max sub-pixel edges; Huber/RANSAC line fits per bar and per lane-line segment; spline for curves.
7. **Curbs.** Height step line, B-spline fitted, optional image-edge snap.
8. **Vectorise** with Douglas-Peucker at 2-3 cm and conservative regularisation.
9. **Evaluate** on a hand-labelled set (~30 scenes incl. a shadowed one and a worn one): P50/P95 distance from extracted to reference geometry per class, plus completeness/correctness. This is the gate for #261.

Expected: pixel-level steps 3-6 with good registration can plausibly hit ~5-10 cm P95 on clean paint; worn/shadowed cases drive the tail. This is an estimate, not a literature value.

## Open questions for the owner

- Height raster cell size and vertical noise? Decides curb snap and whether 5 cm steps are detectable.
- How many drives per ortho pixel and how well are the drives registered to each other? Controls edge blur.
- Is a surveyed or hand-labelled reference available? Needed for P95.

## Sources

- Guan, Li, Yu, Wang, Chapman, Yang (2014), Using mobile laser scanning data for automated extraction of road markings, ISPRS J. Photogramm. Remote Sens. 87:93-107, doi:10.1016/j.isprsjprs.2013.11.005 [read]. PDF: https://uwaterloo.ca/geospatial-intelligence/sites/default/files/uploads/files/using_mobile_laser_scanning_data_for_automated_extraction_of_road_markings.pdf
- Ma, Li, Li, Zhong, Chapman (2019), Generation of horizontally curved driving lines in HD maps using MLS point clouds, IEEE JSTARS, doi:10.1109/JSTARS.2019.2904514 [read]. https://uwaterloo.ca/geospatial-intelligence/sites/default/files/uploads/files/2019-ma-li-li-zhong-chapman-jstars.pdf
- Li, Zhang, Ying, Li (2016), Recognition and reconstruction of zebra crossings on roads from MLS data, ISPRS Int. J. Geo-Inf. 5(7):125, doi:10.3390/ijgi5070125 [read via copy]. https://www.scipedia.com/wd/images/9/9f/Draft_Content_835509304-beopen1224-3690-document.pdf ; https://www.mdpi.com/2220-9964/5/7/125
- Yao et al. (2018), ISPRS Archives XLII-3:2113 [read abstract]. https://isprs-archives.copernicus.org/articles/XLII-3/2113/2018/
- Tian, Zhuo, Auer, Kurz, Reinartz, Fusion of stereo aerial images and official surveying data for mapping curbstones using AI, DLR [read]. https://elib.dlr.de/196561/1/DP169-latex.pdf
- MUTCD 2009 ed. Chapter 3B (crosswalk 6-24 in, stop line 12-24 in) [snippet]. https://mutcd.fhwa.dot.gov/htm/2009/part3/part3b.htm
- Geographical map registration and fusion of lidar-aerial orthoimagery in GIS, arXiv 1904.09047 [snippet only; 15-75 cm figure unverified]. https://arxiv.org/pdf/1904.09047
- Takahashi et al. 2016 (Hough on MLS intensity), Billah & Rahman 2019 (IDW + Otsu) [snippet only].
- Classics [memory]: Otsu 1979 (IEEE TSMC 9:62), Sauvola & Pietikainen 2000 (Pattern Recognition 33:225), Fischler & Bolles 1981 (CACM 24:381), Zhang & Suen 1984 (CACM 27:236), Canny 1986 (IEEE TPAMI 8:679), Steger 1998 (IEEE TPAMI 20:113), Douglas & Peucker 1973 (Cartographica 10:112).
- Library docs: OpenCV (`adaptiveThreshold`, `morphologyEx`, `HoughLinesP`, `minAreaRect`, `fitLine`, `findTransformECC`, `approxPolyDP`), scikit-image (`threshold_sauvola`, `apply_hysteresis_threshold`, `skeletonize`, `measure.ransac`, `approximate_polygon`, `registration.phase_cross_correlation`). Function names from background knowledge; docs.opencv.org returned 403 to the fetch tool.
