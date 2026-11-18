(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  }
  if (root) {
    root.LABELTOOL_PURE = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function () {
  "use strict";

  var CONTROL_VALUES = ["signalised", "stop_controlled", "uncontrolled", "mid_block"];

  function closeRing(xy) {
    if (!Array.isArray(xy) || xy.length === 0) return xy;
    var first = xy[0];
    var last = xy[xy.length - 1];
    if (first && last && first[0] === last[0] && first[1] === last[1]) {
      return xy.slice();
    }
    return xy.slice().concat([first.slice()]);
  }

  function xyToPx(coord, win) {
    var x = coord[0], y = coord[1];
    var x0 = win.x0, y1 = win.y1, g = win.g;
    return [(x - x0) / g, (y1 - y) / g];
  }

  function surfaceToFeature(surface, surfaceMap) {
    if (!surface || typeof surface !== "object") return null;
    var rawType = surface.rawType;
    if (!rawType || !surfaceMap || !surfaceMap[rawType]) return null;
    var mapping = surfaceMap[rawType];
    var element = mapping[0], type = mapping[1];
    var props = (surface.props && typeof surface.props === "object") ? surface.props : {};
    if (props.origin && props.origin !== "operator") return null;

    var xy = surface.xy;
    if (!Array.isArray(xy) || xy.length === 0) return null;
    var isPoly = surface.geom === "polygon" || surface.geom === "Polygon" || element === "crosswalk";
    var pts = xy.map(function (p) { return [p[0], p[1]]; });
    if (isPoly) {
      if (pts.length < 3) return null;
      var distinct = {};
      pts.forEach(function (p) { distinct[p[0] + "," + p[1]] = true; });
      if (Object.keys(distinct).length < 3) return null;
    } else {
      if (pts.length < 2) return null;
    }
    var coords = isPoly ? closeRing(pts) : pts;
    var geometry = isPoly
      ? { type: "Polygon", coordinates: [coords] }
      : { type: "LineString", coordinates: coords };
    var outProps = {};
    for (var k in props) {
      if (Object.prototype.hasOwnProperty.call(props, k)) outProps[k] = props[k];
    }
    outProps.id = surface.id;
    outProps.element = element;
    outProps.type = type;
    outProps.origin = "operator";
    outProps.source_marking_type = rawType;
    outProps.evidence = surface.evidence;
    return { type: "Feature", geometry: geometry, properties: outProps };
  }

  function featureToSurface(feature, window, surfaceMap, schemaFields) {
    if (!feature || typeof feature !== "object") return null;
    var geom = feature.geometry;
    var props = (feature.properties && typeof feature.properties === "object") ? feature.properties : {};
    if (props.origin !== "operator") return null;
    var raw = props.source_marking_type;
    if (!raw || !surfaceMap || !surfaceMap[raw]) return null;
    var xy = null, isPoly = false;
    if (geom && geom.type === "LineString" && Array.isArray(geom.coordinates)) {
      xy = geom.coordinates.map(function (p) { return [p[0], p[1]]; });
      isPoly = false;
    } else if (geom && geom.type === "Polygon" && Array.isArray(geom.coordinates) && Array.isArray(geom.coordinates[0])) {
      var ring = geom.coordinates[0].slice();
      if (ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]) {
        ring = ring.slice(0, -1);
      }
      xy = ring.map(function (p) { return [p[0], p[1]]; });
      isPoly = true;
    } else {
      return null;
    }
    if (!xy || xy.length === 0) return null;
    if (isPoly && xy.length < 3) return null;
    if (!isPoly && xy.length < 2) return null;
    var px = xy.map(function (c) { return xyToPx(c, window); });
    var outProps = {};
    var fields = schemaFields || [];
    for (var i = 0; i < fields.length; i++) {
      var k = fields[i];
      if (Object.prototype.hasOwnProperty.call(props, k)) outProps[k] = props[k];
    }
    return {
      id: props.id,
      rawType: raw,
      geom: isPoly ? "polygon" : "polyline",
      xy: xy,
      px: px,
      evidence: props.evidence,
      props: outProps
    };
  }

  function putBody(version, passthrough, surfaces, surfaceMap) {
    var features = [];
    if (Array.isArray(passthrough)) {
      for (var i = 0; i < passthrough.length; i++) features.push(passthrough[i]);
    }
    if (Array.isArray(surfaces)) {
      for (var j = 0; j < surfaces.length; j++) {
        var f = surfaceToFeature(surfaces[j], surfaceMap);
        if (f) features.push(f);
      }
    }
    return { version: version, feature_collection: { type: "FeatureCollection", features: features } };
  }

  function metaBody(control, notes) {
    return { control: (control === "" ? null : control), notes: notes };
  }

  function changeSurfaceType(surface, rawType, surfaceMap) {
    if (!surface || !surfaceMap || !surfaceMap[rawType]) return null;
    var mapping = surfaceMap[rawType];
    var element = mapping[0], type = mapping[1];
    var isPoly = surface.geom === "polygon" || surface.geom === "Polygon" || element === "crosswalk";
    var pts = Array.isArray(surface.xy) ? surface.xy : [];
    var distinct = {};
    pts.forEach(function (p) { distinct[p[0] + "," + p[1]] = true; });
    if (isPoly) {
      if (Object.keys(distinct).length < 3) return null;
    } else {
      if (pts.length < 2) return null;
    }
    var out = JSON.parse(JSON.stringify(surface));
    out.rawType = rawType;
    if (out.props && typeof out.props === "object") {
      out.props.element = element;
      out.props.type = type;
      out.props.source_marking_type = rawType;
    }
    return out;
  }

  function nextTraceType(state, rawType) {
    var out = {};
    for (var k in state) {
      if (Object.prototype.hasOwnProperty.call(state, k)) out[k] = state[k];
    }
    out.nextType = rawType;
    if (Array.isArray(state.surfaces)) out.surfaces = state.surfaces.slice();
    return out;
  }

  function editsAllowed(meta, loaded) {
    return Boolean(loaded && meta && !meta.frozen);
  }

  function siteSummary(meta) {
    if (!meta) return "Draft: editable.";
    if (meta.frozen) {
      return "Frozen " + (meta.approved_at || "") + " by " + (meta.approved_by || "");
    }
    return "Draft: editable.";
  }

  return {
    CONTROL_VALUES: CONTROL_VALUES,
    closeRing: closeRing,
    xyToPx: xyToPx,
    surfaceToFeature: surfaceToFeature,
    featureToSurface: featureToSurface,
    putBody: putBody,
    metaBody: metaBody,
    changeSurfaceType: changeSurfaceType,
    nextTraceType: nextTraceType,
    editsAllowed: editsAllowed,
    siteSummary: siteSummary
  };
});
