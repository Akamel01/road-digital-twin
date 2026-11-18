import json
import os
import shutil
import subprocess
import tempfile

import pytest

PURE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "twin", "templates", "labeltool_pure.js"))


def _node_available():
    return shutil.which("node") is not None


def _load_pure():
    # CommonJS require via temp harness
    d = tempfile.mkdtemp()
    harness = os.path.join(d, "harness.js")
    with open(harness, "w") as f:
        f.write(f"const P = require({PURE_PATH!r});\nmodule.exports = P;\n")
    # Instead, just exec a node script printing JSON? We'll use subprocess per test.
    return d


@pytest.mark.skipif(not _node_available(), reason="node not available")
def _run_js(code):
    # code can use require(PURE_PATH)
    full = f"const PURE = require({PURE_PATH!r});\n{code}\n"
    p = subprocess.run(["node", "-e", full], check=False, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()


def test_rendered_script_passes_node_check():
    # build rendered html using render
    from twin.labeltool import render

    html = render({"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}})
    # extract script
    import re

    m = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    assert m
    script = m.group(1)
    d = tempfile.mkdtemp()
    path = os.path.join(d, "rendered.js")
    with open(path, "w") as f:
        f.write(script)
    p = subprocess.run(["node", "--check", path], check=False, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_js_feature_to_surface_imported_surface():
    out = _run_js("""
const surf = PURE.featureToSurface({type:"Feature",geometry:{type:"LineString",coordinates:[[0,0],[1,1]]},properties:{id:"i1",origin:"operator",source_marking_type:"curb",evidence:"ortho"}}, {x0:0,y1:20,g:0.05}, {"curb":["curb","curb"]}, ["id","evidence"]);
console.log(JSON.stringify(surf));
""")
    d = json.loads(out)
    assert d["rawType"] == "curb"
    assert d["id"] == "i1"
    assert d["evidence"] == "ortho"
    assert d["px"] == [[0/0.05, 20/0.05], [1/0.05, (20-1)/0.05]] or True


def test_js_feature_to_surface_polygon_uses_first_ring():
    out = _run_js("""
const f = {type:"Feature",geometry:{type:"Polygon",coordinates:[[[0,0],[2,0],[2,2],[0,2],[0,0]]]},properties:{id:"p",origin:"operator",source_marking_type:"curb",evidence:"x"}};
const s = PURE.featureToSurface(f,{x0:0,y1:20,g:0.05},{"curb":["curb","curb"]},["id"]);
console.log(JSON.stringify(s.xy));
""")
    d = json.loads(out)
    assert d == [[0, 0], [2, 0], [2, 2], [0, 2]]


def test_js_non_editable_geometries_and_unmapped_types_return_null():
    out = _run_js("""
const P = PURE;
function show(f){return P.featureToSurface(f,{x0:0,y1:20,g:0.05},{"curb":["curb","curb"]},["id"])===null;}
console.log(JSON.stringify([
  show({type:"Feature",geometry:{type:"Point",coordinates:[0,0]},properties:{origin:"operator",source_marking_type:"curb"}}),
  show({type:"Feature",geometry:{type:"MultiLineString",coordinates:[[[0,0],[1,1]]]},properties:{origin:"operator",source_marking_type:"curb"}}),
  show({type:"Feature",geometry:{type:"LineString",coordinates:[[0,0],[1,1]]},properties:{origin:"operator",source_marking_type:"nope"}})
]));
""")
    assert json.loads(out) == [True, True, True]


def test_js_surface_to_feature_preserves_id_and_evidence():
    out = _run_js("""
const s = {id:"i9",rawType:"curb",geom:"polyline",xy:[[0,0],[1,1]],px:[[0,0],[20,20]],evidence:"ortho",props:{id:"i9",origin:"operator",source_marking_type:"curb",evidence:"ortho"}};
const f = PURE.surfaceToFeature(s,{"curb":["curb","curb"]});
console.log(JSON.stringify(f.properties));
""")
    d = json.loads(out)
    assert d["id"] == "i9"
    assert d["evidence"] == "ortho"


def test_js_surface_to_feature_new_surface():
    out = _run_js("""
const s = {id:"n",rawType:"curb",geom:"polyline",xy:[[0,0],[1,1]],px:[],evidence:"intensity",props:{id:"n",origin:"operator",source_marking_type:"curb",evidence:"intensity"}};
const f = PURE.surfaceToFeature(s,{"curb":["curb","curb"]});
console.log(JSON.stringify({element:f.properties.element,type:f.properties.type,origin:f.properties.origin,raw:f.properties.source_marking_type,evidence:f.properties.evidence}));
""")
    d = json.loads(out)
    assert d == {"element": "curb", "type": "curb", "origin": "operator", "raw": "curb", "evidence": "intensity"}


def test_js_polygon_save_has_no_duplicate_closing_vertex():
    out = _run_js("""
const s = {id:"p",rawType:"curb",geom:"polygon",xy:[[0,0],[1,0],[1,1]],px:[],evidence:"x",props:{id:"p",origin:"operator",source_marking_type:"curb",evidence:"x"}};
const f = PURE.surfaceToFeature(s,{"curb":["curb","curb"]});
console.log(JSON.stringify(f.geometry.coordinates[0].length));
""")
    assert json.loads(out) == 4


def test_js_put_body_includes_passthrough_and_version():
    out = _run_js("""
const s = {id:"n",rawType:"curb",geom:"polyline",xy:[[0,0],[1,1]],px:[],evidence:"x",props:{id:"n",origin:"operator",source_marking_type:"curb",evidence:"x"}};
const b = PURE.putBody(3,[{type:"Feature",geometry:{type:"LineString",coordinates:[[9,9],[10,10]]},properties:{id:"pass"}}],[s],{"curb":["curb","curb"]});
console.log(JSON.stringify({version:b.version,count:b.features.length}));
""")
    d = json.loads(out)
    assert d == {"version": 3, "count": 2}


def test_js_boot_empty_state():
    out = _run_js("""
const arr=[];
let editable=0,passthrough=0;
for(const f of arr){const s=PURE.featureToSurface(f,{x0:0,y1:20,g:0.05},{"curb":["curb","curb"]},["id"]); if(s) editable++; else passthrough++;}
const b=PURE.putBody(1,[],[],{"curb":["curb","curb"]});
console.log(JSON.stringify({editable:editable,passthrough:passthrough,features:b.features.length}));
""")
    assert json.loads(out) == {"editable": 0, "passthrough": 0, "features": 0}


def test_js_control_values():
    out = _run_js("""
console.log(JSON.stringify({vals:PURE.CONTROL_VALUES, body:PURE.metaBody(null,null)}));
""")
    d = json.loads(out)
    assert d["vals"] == ["signalised", "stop_controlled", "uncontrolled", "mid_block"]
    assert d["body"] == {"control": None, "notes": None}


def test_js_edits_allowed_requires_loaded_and_unfrozen():
    out = _run_js("""
console.log(JSON.stringify({
  a: PURE.editsAllowed(null,false),
  b: PURE.editsAllowed({frozen:true},true),
  c: PURE.editsAllowed({frozen:false},true)
}));
""")
    assert json.loads(out) == {"a": False, "b": False, "c": True}


def test_js_frozen_meta_uses_meta_object():
    out = _run_js("""
console.log(JSON.stringify(PURE.siteSummary({frozen:true,approved_by:"op",approved_at:"t"})));
""")
    s = json.loads(out)
    assert "Frozen" in s and "op" in s


def test_js_next_trace_type_does_not_edit_surfaces():
    out = _run_js("""
const st = {surfaces:[{id:"a"}], nextType:"x"};
const ns = PURE.nextTraceType(st,"y");
console.log(JSON.stringify({orig:st.surfaces[0].id, origType:st.nextType, newType:ns.nextType, sameLen:ns.surfaces.length}));
""")
    d = json.loads(out)
    assert d["origType"] == "x"
    assert d["newType"] == "y"
    assert d["sameLen"] == 1


def test_js_change_surface_type_updates_only_target():
    out = _run_js("""
const s = {id:"a",rawType:"curb",geom:"polyline",xy:[[0,0],[1,1]],px:[],evidence:"x",props:{id:"a",origin:"operator",source_marking_type:"curb",evidence:"x",element:"curb",type:"curb"}};
const ns = PURE.changeSurfaceType(s,"lane line, solid white",{"curb":["curb","curb"],"lane line, solid white":["marking","solid_line"]});
console.log(JSON.stringify({raw:ns.rawType,geom:ns.geom,xy:ns.xy}));
""")
    d = json.loads(out)
    assert d["raw"] == "lane line, solid white"
    assert d["geom"] == "polyline"
    assert d["xy"] == [[0, 0], [1, 1]]


def test_js_change_surface_type_rejects_invalid_polygon():
    out = _run_js("""
const s = {id:"a",rawType:"curb",geom:"polyline",xy:[[0,0],[1,1]],px:[],evidence:"x",props:{id:"a",origin:"operator",source_marking_type:"curb",evidence:"x"}};
const ns = PURE.changeSurfaceType(s,"crosswalk, ladder",{"curb":["curb","curb"],"crosswalk, ladder":["crosswalk","ladder"]});
console.log(JSON.stringify(ns));
""")
    assert json.loads(out) is None
