#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>
#include <stdio.h>

/* All buffers are bounded; unsupported inputs return None to the authoritative
 * Python adapter. The optional executor calls only the current row's user
 * callback; no future row is evaluated by this module. */
#define CAP 65536
#define SAFE_INT 9007199254740991LL
typedef struct { char bytes[CAP]; Py_ssize_t size; int ok; } Buffer;
typedef struct {
    PyObject_HEAD
    PyObject *run_id, *market, *market_json, *run_json, *bar_type, *obs_type;
    PyObject *sha256, *revision, *zero, *one;
    PyObject *object_new, *bar_names, *obs_names, *bar_slots, *obs_slots, *transcript_update;
    PyObject *output_models, *output_kind, *output_specs;
    unsigned long long built, fallback;
} Factory;

static void put(Buffer *b, const char *p, Py_ssize_t n) {
    if (!b->ok || n < 0 || n > CAP - b->size) { b->ok = 0; return; }
    memcpy(b->bytes + b->size, p, (size_t)n); b->size += n;
}
static void lit(Buffer *b, const char *p) { put(b, p, (Py_ssize_t)strlen(p)); }
static int ascii_text(PyObject *o) {
    return o && PyUnicode_CheckExact(o) && PyUnicode_IS_ASCII(o) && PyUnicode_GET_LENGTH(o) <= 128;
}
static int safe_int(PyObject *o, long long *out) {
    int overflow = 0;
    if (!o || !PyLong_CheckExact(o)) return 0;
    *out = PyLong_AsLongLongAndOverflow(o, &overflow);
    return !overflow && !PyErr_Occurred() && *out >= -SAFE_INT && *out <= SAFE_INT;
}
static void number(Buffer *b, long long n) {
    char text[32]; int size = snprintf(text, sizeof(text), "%lld", n);
    put(b, text, size);
}
static void string(Buffer *b, PyObject *o) {
    static const char hex[] = "0123456789abcdef";
    const unsigned char *s = PyUnicode_1BYTE_DATA(o);
    Py_ssize_t n = PyUnicode_GET_LENGTH(o);
    lit(b, "\"");
    for (Py_ssize_t i = 0; i < n; ++i) {
        unsigned char c = s[i];
        if (c == '"' || c == '\\') { lit(b, "\\"); put(b, (const char *)&c, 1); }
        else if (c == '\b') lit(b, "\\b");
        else if (c == '\f') lit(b, "\\f");
        else if (c == '\n') lit(b, "\\n");
        else if (c == '\r') lit(b, "\\r");
        else if (c == '\t') lit(b, "\\t");
        else if (c < 32 || c == 127) {
            char escape[] = {'\\','u','0','0',hex[c >> 4],hex[c & 15]}; put(b, escape, 6);
        } else put(b, (const char *)&c, 1);
    }
    lit(b, "\"");
}
static int primitive(Buffer *b, PyObject *o) {
    long long value;
    if (ascii_text(o)) string(b, o);
    else if (o == Py_None) lit(b, "null");
    else if (o == Py_True) lit(b, "true");
    else if (o == Py_False) lit(b, "false");
    else if (safe_int(o, &value)) number(b, value);
    else return 0;
    return b->ok;
}
static int flat_dict(Buffer *b, PyObject *mapping) {
    if (!PyDict_CheckExact(mapping) || PyDict_Size(mapping) > 32) return 0;
    PyObject *keys = PyDict_Keys(mapping);
    if (!keys) return -1;
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(keys); ++i) {
        if (!ascii_text(PyList_GET_ITEM(keys, i))) { Py_DECREF(keys); return 0; }
    }
    if (PyList_Sort(keys) < 0) { Py_DECREF(keys); return -1; }
    lit(b, "{");
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(keys); ++i) {
        PyObject *key = PyList_GET_ITEM(keys, i), *value = PyDict_GetItemWithError(mapping, key);
        if (!value) { Py_DECREF(keys); return PyErr_Occurred() ? -1 : 0; }
        if (i) lit(b, ",");
        string(b, key); lit(b, ":");
        if (!primitive(b, value)) { Py_DECREF(keys); return PyErr_Occurred() ? -1 : 0; }
    }
    lit(b, "}"); Py_DECREF(keys); return b->ok;
}
static int canonical_decimal(PyObject *o) {
    if (!ascii_text(o)) return 0;
    const unsigned char *s = PyUnicode_1BYTE_DATA(o);
    Py_ssize_t n = PyUnicode_GET_LENGTH(o), i = 0;
    if (!n) return 0;
    if (s[i] == '-') ++i;
    if (i == n || s[i] < '0' || s[i] > '9') return 0;
    if (s[i] == '0') ++i;
    else { while (i < n && s[i] >= '0' && s[i] <= '9') ++i; }
    if (i < n && s[i] == '.') {
        ++i; Py_ssize_t start = i;
        while (i < n && s[i] >= '0' && s[i] <= '9') ++i;
        if (i == start) return 0;
    }
    return i == n;
}
static PyObject *clock_value(Factory *f, PyObject *bar, const char *snake, const char *camel) {
    PyObject *value = PyDict_GetItemString(bar, snake); long long n;
    if (value && value != Py_None) {
        if (!safe_int(value, &n)) return NULL;
        if (n != 0) return value;
    }
    value = PyDict_GetItemString(bar, camel);
    if (!value || value == Py_None) return f->zero;
    return safe_int(value, &n) ? value : NULL;
}
static int visit_factory(Factory *f, visitproc visit, void *arg) {
    Py_VISIT(f->run_id); Py_VISIT(f->market); Py_VISIT(f->market_json); Py_VISIT(f->run_json);
    Py_VISIT(f->bar_type); Py_VISIT(f->obs_type); Py_VISIT(f->sha256);
    Py_VISIT(f->revision); Py_VISIT(f->zero); Py_VISIT(f->one);
    Py_VISIT(f->object_new); Py_VISIT(f->bar_names); Py_VISIT(f->obs_names);
    Py_VISIT(f->bar_slots); Py_VISIT(f->obs_slots); Py_VISIT(f->transcript_update);
    Py_VISIT(f->output_models); Py_VISIT(f->output_kind); Py_VISIT(f->output_specs); return 0;
}
static int clear_factory(Factory *f) {
    Py_CLEAR(f->sha256);
    Py_CLEAR(f->run_id); Py_CLEAR(f->market); Py_CLEAR(f->market_json); Py_CLEAR(f->run_json);
    Py_CLEAR(f->bar_type); Py_CLEAR(f->obs_type);
    Py_CLEAR(f->revision); Py_CLEAR(f->zero); Py_CLEAR(f->one);
    Py_CLEAR(f->object_new); Py_CLEAR(f->bar_names); Py_CLEAR(f->obs_names);
    Py_CLEAR(f->bar_slots); Py_CLEAR(f->obs_slots); Py_CLEAR(f->transcript_update);
    Py_CLEAR(f->output_models); Py_CLEAR(f->output_kind); Py_CLEAR(f->output_specs); return 0;
}
static void destroy_factory(Factory *f) {
    PyTypeObject *type = Py_TYPE(f);
    PyObject_GC_UnTrack(f); clear_factory(f); type->tp_free((PyObject *)f); Py_DECREF(type);
}
static PyObject *capture_slots(PyObject *type, PyObject *names) {
    if (!PyType_Check(type)) { PyErr_SetString(PyExc_ValueError, "SDK class must be a Python type"); return NULL; }
    PyObject *slots = PyTuple_New(PyTuple_GET_SIZE(names)); if (!slots) return NULL;
    for (Py_ssize_t i=0; i<PyTuple_GET_SIZE(names); ++i) {
        PyObject *slot = _PyType_Lookup((PyTypeObject *)type, PyTuple_GET_ITEM(names, i));
        if (!slot || !Py_IS_TYPE(slot, &PyMemberDescr_Type) || PyDescr_TYPE(slot) != (PyTypeObject *)type) {
            Py_DECREF(slots); PyErr_SetString(PyExc_ValueError, "SDK slot layout is not supported"); return NULL;
        }
        PyTuple_SET_ITEM(slots, i, Py_NewRef(slot));
    }
    return slots;
}
static int slots_unchanged(PyObject *type, PyObject *names, PyObject *slots) {
    for (Py_ssize_t i=0; i<PyTuple_GET_SIZE(names); ++i)
        if (_PyType_Lookup((PyTypeObject *)type, PyTuple_GET_ITEM(names, i)) != PyTuple_GET_ITEM(slots, i)) return 0;
    return 1;
}
static int initialize_factory(Factory *f, PyObject *args, PyObject *kwargs) {
    PyObject *run, *market, *bar_type, *obs_type, *hashlib = NULL;
    if (f->sha256) { PyErr_SetString(PyExc_RuntimeError, "row factory is already initialized"); return -1; }
    if (!PyArg_ParseTuple(args, "OOOO", &run, &market, &bar_type, &obs_type)) return -1;
    if (kwargs && PyDict_Size(kwargs)) { PyErr_SetString(PyExc_TypeError, "positional arguments only"); return -1; }
    if (!ascii_text(run) || !PyDict_CheckExact(market) || PyDict_Size(market) > 8 ||
        !PyCallable_Check(bar_type) || !PyCallable_Check(obs_type)) {
        PyErr_SetString(PyExc_ValueError, "unsupported native row factory metadata"); return -1;
    }
    Py_ssize_t pos = 0; PyObject *k, *v;
    while (PyDict_Next(market, &pos, &k, &v)) {
        if (!ascii_text(k) || !ascii_text(v)) { PyErr_SetString(PyExc_ValueError, "unsupported market metadata"); return -1; }
    }
    Buffer encoded = {{0}, 0, 1}, run_encoded = {{0}, 0, 1};
    int result = flat_dict(&encoded, market);
    if (result != 1) { if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "market encoding failed"); return -1; }
    string(&run_encoded, run);
    clear_factory(f);
    f->run_id = Py_NewRef(run);
#define OWN(field, expression) do { f->field = (expression); if (!f->field) goto init_failed; } while (0)
    OWN(market, PyDict_Copy(market));
    OWN(market_json, PyBytes_FromStringAndSize(encoded.bytes, encoded.size));
    OWN(run_json, PyBytes_FromStringAndSize(run_encoded.bytes, run_encoded.size));
    f->bar_type = Py_NewRef(bar_type); f->obs_type = Py_NewRef(obs_type);
    OWN(revision, PyUnicode_FromString("python-source"));
    OWN(zero, PyLong_FromLong(0)); OWN(one, PyLong_FromLong(1));
    OWN(object_new, PyObject_GetAttrString((PyObject *)&PyBaseObject_Type, "__new__"));
    OWN(bar_names, Py_BuildValue("(sssssss)", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"));
    OWN(obs_names, Py_BuildValue("(ssssssssssss)", "run_id", "revision_id", "generation", "sequence", "event_time_ms",
                                "watermark_ms", "phase", "market", "bar", "features", "account_view", "input_hash"));
    OWN(bar_slots, capture_slots(bar_type, f->bar_names));
    OWN(obs_slots, capture_slots(obs_type, f->obs_names));
    hashlib = PyImport_ImportModule("hashlib");
    if (hashlib) { f->sha256 = PyObject_GetAttrString(hashlib, "sha256"); Py_DECREF(hashlib); }
    if (!f->sha256) goto init_failed;
    return 0;
init_failed:
    clear_factory(f); return -1;
#undef OWN
}
static PyObject *slot_object(Factory *f, PyObject *type, PyObject *slots, PyObject *values) {
    /* object.__new__ performs the safety checks for Python heap types; do not
     * call GenericAlloc on arbitrary extension types. Field order is the SDK
     * dataclass initializer's order. The caller verifies the SDK signature. */
    PyObject *object = PyObject_CallOneArg(f->object_new, type);
    if (!object) return NULL;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(slots); ++i) {
        PyObject *slot = PyTuple_GET_ITEM(slots, i);
        if (Py_TYPE(slot)->tp_descr_set(slot, object, PyTuple_GET_ITEM(values, i)) < 0) {
            Py_DECREF(object); return NULL;
        }
    }
    return object;
}
static PyObject *build_row(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    static const char *fields[] = {"open", "high", "low", "close", "volume"};
    PyObject *raw = NULL, *sequence, *stamp, *phase, *values[5] = {NULL}, *opened = NULL, *closed = NULL;
    PyObject *features = NULL, *input_bytes = NULL, *hash = NULL, *digest = NULL, *input_hash = NULL;
    PyObject *bar_args = NULL, *bar = NULL, *market = NULL, *account = NULL, *obs_args = NULL, *obs = NULL, *wire = NULL, *result = NULL;
    Buffer *storage = NULL;
    long long seq_n, time_n, open_n, close_n;
    if (nargs != 4) { PyErr_SetString(PyExc_TypeError, "build requires bar, sequence, time, phase"); return NULL; }
    if (!f->sha256) { PyErr_SetString(PyExc_RuntimeError, "uninitialized row factory"); return NULL; }
    if (!slots_unchanged(f->bar_type, f->bar_names, f->bar_slots) || !slots_unchanged(f->obs_type, f->obs_names, f->obs_slots)) goto fallback;
    sequence = args[1]; stamp = args[2]; phase = args[3];
    if (!PyDict_CheckExact(args[0]) || PyDict_Size(args[0]) > 32 || !safe_int(sequence, &seq_n) || !safe_int(stamp, &time_n) || !ascii_text(phase)) goto fallback;
    raw = PyDict_Copy(args[0]); if (!raw) goto done;
    Py_ssize_t position = 0; PyObject *key, *value; long long ignored_number;
    while (PyDict_Next(raw, &position, &key, &value)) {
        if (!ascii_text(key) || !(ascii_text(value) || value == Py_None || value == Py_True || value == Py_False || safe_int(value, &ignored_number))) goto fallback;
    }
    for (int i = 0; i < 5; ++i) {
        value = PyDict_GetItemString(raw, fields[i]);
        if (!canonical_decimal(value)) goto fallback;
        values[i] = Py_NewRef(value);
    }
    opened = clock_value(f, raw, "open_time_ms", "openTimeMs");
    Py_XINCREF(opened);
    closed = clock_value(f, raw, "close_time_ms", "closeTimeMs");
    Py_XINCREF(closed);
    if (!opened || !closed || !safe_int(opened, &open_n) || !safe_int(closed, &close_n)) goto fallback;
    storage = PyMem_Malloc(sizeof(Buffer) * 3);
    if (!storage) { PyErr_NoMemory(); goto done; }
    for (int i = 0; i < 3; ++i) { storage[i].size = 0; storage[i].ok = 1; }
#define host storage[0]
#define feature_json storage[1]
#define body storage[2]
    lit(&host, "{\"bar\":");
    int flat = flat_dict(&host, raw);
    if (flat < 0) goto done;
    if (!flat) goto fallback;
    features = PyDict_New(); if (!features) goto done;
    for (int i = 0; i < 5; ++i) if (PyDict_SetItemString(features, fields[i], values[i]) < 0) goto done;
    flat = flat_dict(&feature_json, features);
    if (flat < 0) goto done;
    if (!flat) goto fallback;
    lit(&host, ",\"features\":"); put(&host, feature_json.bytes, feature_json.size);
    lit(&host, ",\"sequence\":"); number(&host, seq_n);
    lit(&host, ",\"trade\":null,\"watermark\":"); number(&host, time_n); lit(&host, "}");
    if (!host.ok) goto fallback;
    input_bytes = PyBytes_FromStringAndSize(host.bytes, host.size); if (!input_bytes) goto done;
    hash = PyObject_CallOneArg(f->sha256, input_bytes); if (!hash) goto done;
    digest = PyObject_CallMethod(hash, "hexdigest", NULL); if (!digest) goto done;
    if (!ascii_text(digest) || PyUnicode_GET_LENGTH(digest) != 64) {
        PyErr_SetString(PyExc_ValueError, "invalid SHA256 implementation result"); goto done;
    }
    input_hash = PyUnicode_FromFormat("sha256:%U", digest); if (!input_hash) goto done;
    lit(&body, "{\"accountView\":{},\"bar\":{\"close\":"); string(&body, values[3]);
    lit(&body, ",\"closeTimeMs\":"); number(&body, close_n);
    lit(&body, ",\"high\":"); string(&body, values[1]); lit(&body, ",\"low\":"); string(&body, values[2]);
    lit(&body, ",\"open\":"); string(&body, values[0]); lit(&body, ",\"openTimeMs\":"); number(&body, open_n);
    lit(&body, ",\"volume\":"); string(&body, values[4]);
    lit(&body, "},\"eventTimeMs\":"); number(&body, time_n);
    lit(&body, ",\"features\":"); put(&body, feature_json.bytes, feature_json.size);
    lit(&body, ",\"generation\":1,\"inputHash\":"); string(&body, input_hash);
    lit(&body, ",\"market\":"); put(&body, PyBytes_AS_STRING(f->market_json), PyBytes_GET_SIZE(f->market_json));
    lit(&body, ",\"phase\":"); string(&body, phase);
    lit(&body, ",\"revisionId\":\"python-source\",\"runId\":"); put(&body, PyBytes_AS_STRING(f->run_json), PyBytes_GET_SIZE(f->run_json));
    lit(&body, ",\"schemaVersion\":\"candlescope.python-strategy-observation/1\",\"sequence\":"); number(&body, seq_n);
    lit(&body, ",\"watermarkMs\":"); number(&body, time_n); lit(&body, "}");
    if (!body.ok) goto fallback;
    bar_args = PyTuple_Pack(7, opened, closed, values[0], values[1], values[2], values[3], values[4]); if (!bar_args) goto done;
    bar = slot_object(f, f->bar_type, f->bar_slots, bar_args); if (!bar) goto done;
    market = PyDict_Copy(f->market); account = PyDict_New(); if (!market || !account) goto done;
    obs_args = PyTuple_Pack(12, f->run_id, f->revision, f->one, sequence, stamp, stamp,
                            phase, market, bar, features, account, input_hash); if (!obs_args) goto done;
    obs = slot_object(f, f->obs_type, f->obs_slots, obs_args); if (!obs) goto done;
    wire = PyBytes_FromStringAndSize(body.bytes, body.size); if (!wire) goto done;
    result = PyTuple_Pack(2, obs, wire); if (result) ++f->built;
    goto done;
fallback:
    if (!PyErr_Occurred()) { ++f->fallback; result = Py_NewRef(Py_None); }
done:
    PyMem_Free(storage);
    Py_XDECREF(opened); Py_XDECREF(closed);
    for (int i = 0; i < 5; ++i) Py_XDECREF(values[i]);
    Py_XDECREF(raw);
    Py_XDECREF(features); Py_XDECREF(input_bytes); Py_XDECREF(hash); Py_XDECREF(digest); Py_XDECREF(input_hash);
    Py_XDECREF(bar_args); Py_XDECREF(bar); Py_XDECREF(market); Py_XDECREF(account); Py_XDECREF(obs_args); Py_XDECREF(obs); Py_XDECREF(wire);
    return result;
#undef host
#undef feature_json
#undef body
}
static PyObject *factory_stats(Factory *f, PyObject *ignored) {
    return Py_BuildValue("{sK,sK}", "built", f->built, "fallback", f->fallback);
}
static PyObject *bind_transcript(Factory *f, PyObject *hash) {
    if (f->transcript_update) { PyErr_SetString(PyExc_RuntimeError, "transcript already bound"); return NULL; }
    PyObject *method = PyObject_GetAttrString(hash, "update");
    if (!method) return NULL;
    if (!PyCallable_Check(method)) { Py_DECREF(method); PyErr_SetString(PyExc_TypeError, "hash update must be callable"); return NULL; }
    f->transcript_update = method; Py_RETURN_NONE;
}
static PyObject *record_impl(Factory *f, PyObject *const *args, Py_ssize_t nargs, int success) {
    long long id; PyObject *wire = NULL, *result = NULL, *hash = NULL, *digest = NULL;
    Buffer *previous = NULL;
    if (nargs != 5 || !safe_int(args[0], &id) || id < 1 ||
        (args[1] != Py_True && args[1] != Py_False) || !PyBytes_CheckExact(args[2]) || !PyBytes_CheckExact(args[3])) {
        PyErr_SetString(PyExc_TypeError, "invalid V1 record arguments"); return NULL;
    }
    Py_ssize_t obs_len = PyBytes_GET_SIZE(args[2]), response_len = PyBytes_GET_SIZE(args[3]);
    if (obs_len > 65536 || response_len > 3*262144) { PyErr_SetString(PyExc_ValueError, "V1 record exceeds qualified bounds"); return NULL; }
    int bound = args[4] != Py_None;
    if ((bound && (!ascii_text(args[4]) || !f->sha256)) || (!bound && !f->transcript_update)) {
        PyErr_SetString(PyExc_ValueError, "invalid V1 transcript state"); return NULL;
    }
    const char *a = "{\"request\":{\"id\":";
    const char *b = args[1] == Py_True ? ",\"method\":\"warmup\",\"params\":{\"observation\":" : ",\"method\":\"step\",\"params\":{\"observation\":";
    const char *c = "}},\"response\":";
    char id_text[32]; int id_len = snprintf(id_text, sizeof(id_text), "%lld", id);
    char prefix[96]; int prefix_len = success ? snprintf(prefix, sizeof(prefix), "{\"id\":%lld,\"ok\":true,\"result\":", id) : 0;
    Py_ssize_t record_len = (Py_ssize_t)strlen(a) + id_len + (Py_ssize_t)strlen(b) + obs_len + (Py_ssize_t)strlen(c) + prefix_len + response_len + success + 1;
    Py_ssize_t total = record_len + ((!bound && id > 1) ? 1 : 0);
    if (bound) {
        previous = PyMem_Malloc(sizeof(Buffer)); if (!previous) return PyErr_NoMemory();
        previous->size=0; previous->ok=1; string(previous, args[4]);
        total += 12 + previous->size + 10 + 1; /* {"previous": + ,"record": + } */
    }
    wire = PyBytes_FromStringAndSize(NULL, total); if (!wire) goto record_done;
    char *cursor = PyBytes_AS_STRING(wire);
#define PART(s,n) do { memcpy(cursor, (s), (size_t)(n)); cursor += (n); } while (0)
    if (bound) { PART("{\"previous\":", 12); PART(previous->bytes, previous->size); PART(",\"record\":", 10); }
    else if (id > 1) { PART(",", 1); }
    PART(a, strlen(a)); PART(id_text, id_len); PART(b, strlen(b)); PART(PyBytes_AS_STRING(args[2]), obs_len);
    PART(c, strlen(c));
    if (success) { PART(prefix, prefix_len); }
    PART(PyBytes_AS_STRING(args[3]), response_len);
    if (success) { PART("}", 1); }
    PART("}", 1);
    if (bound) { PART("}", 1); }
#undef PART
    if (cursor - PyBytes_AS_STRING(wire) != total) { PyErr_SetString(PyExc_SystemError, "V1 record length mismatch"); goto record_done; }
    if (!bound) result = PyObject_CallOneArg(f->transcript_update, wire);
    else {
        hash = PyObject_CallOneArg(f->sha256, wire); if (!hash) goto record_done;
        digest = PyObject_CallMethod(hash, "hexdigest", NULL); if (!digest) goto record_done;
        result = PyUnicode_FromFormat("sha256:%U", digest);
    }
record_done:
    PyMem_Free(previous); Py_XDECREF(wire); Py_XDECREF(hash); Py_XDECREF(digest); return result;
}
static PyObject *record_v1(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    return record_impl(f, args, nargs, 0);
}
static PyObject *record_success(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    return record_impl(f, args, nargs, 1);
}

static PyObject *empty_decision_hash(PyObject *module, PyObject *const *args, Py_ssize_t nargs) {
    long long sequence, stamp;
    if (nargs != 4) { PyErr_SetString(PyExc_TypeError, "empty_decision_hash requires previous, sequence, watermark, sha256"); return NULL; }
    if (!ascii_text(args[0]) || !safe_int(args[1], &sequence) || !safe_int(args[2], &stamp)) Py_RETURN_NONE;
    Buffer *b = PyMem_Malloc(sizeof(Buffer)); if (!b) return PyErr_NoMemory();
    b->size=0; b->ok=1;
    lit(b, "{\"decision\":{\"intents\":[],\"sequence\":"); number(b, sequence);
    lit(b, ",\"watermark_ms\":"); number(b, stamp);
    lit(b, "},\"previous\":"); string(b, args[0]); lit(b, "}");
    PyObject *wire = PyBytes_FromStringAndSize(b->bytes, b->size);
    PyMem_Free(b);
    if (!wire) return NULL;
    PyObject *hash = PyObject_CallOneArg(args[3], wire); Py_DECREF(wire);
    if (!hash) return NULL;
    PyObject *digest = PyObject_CallMethod(hash, "hexdigest", NULL); Py_DECREF(hash);
    if (!digest) return NULL;
    if (!ascii_text(digest) || PyUnicode_GET_LENGTH(digest) != 64) {
        Py_DECREF(digest); PyErr_SetString(PyExc_ValueError, "invalid SHA256 result"); return NULL;
    }
    PyObject *result = PyUnicode_FromFormat("sha256:%U", digest); Py_DECREF(digest); return result;
}
static PyObject *encode_output(Factory *f, PyObject *const *args, Py_ssize_t nargs, int host_parts) {
    PyObject *sequence, *kind, *payload = NULL, *schema, *key, *value;
    PyObject *input = NULL, *hash = NULL, *digest = NULL, *full_hash = NULL, *encoded = NULL, *result = NULL;
    PyObject *state_hash = NULL, *host_args = NULL;
    Buffer *buffers = NULL; long long seq; Py_ssize_t position = 0;
    if (nargs != (host_parts ? 5 : 4)) { PyErr_SetString(PyExc_TypeError, "invalid output encoder arguments"); return NULL; }
    if (!f->sha256) { PyErr_SetString(PyExc_RuntimeError, "uninitialized row factory"); return NULL; }
    sequence = args[0]; kind = args[1]; schema = args[3];
    if (!safe_int(sequence, &seq) || !ascii_text(kind) || !ascii_text(schema) ||
        !PyDict_CheckExact(args[2]) || PyDict_Size(args[2]) > 8) goto fallback_output;
    if (memchr(PyUnicode_1BYTE_DATA(kind), 127, (size_t)PyUnicode_GET_LENGTH(kind)) ||
        memchr(PyUnicode_1BYTE_DATA(schema), 127, (size_t)PyUnicode_GET_LENGTH(schema))) goto fallback_output;
    payload = PyDict_Copy(args[2]); if (!payload) goto done_output;
    while (PyDict_Next(payload, &position, &key, &value)) {
        if (!ascii_text(key) || !ascii_text(value) ||
            memchr(PyUnicode_1BYTE_DATA(key), 127, (size_t)PyUnicode_GET_LENGTH(key)) ||
            memchr(PyUnicode_1BYTE_DATA(value), 127, (size_t)PyUnicode_GET_LENGTH(value))) goto fallback_output;
    }
    buffers = PyMem_Malloc(sizeof(Buffer) * 3); if (!buffers) { PyErr_NoMemory(); goto done_output; }
    for (int i=0; i<3; ++i) { buffers[i].size=0; buffers[i].ok=1; }
    int flat_output = flat_dict(&buffers[0], payload);
    if (flat_output < 0) goto done_output;
    if (!flat_output) goto fallback_output;
    Buffer *a=&buffers[1], *b=&buffers[2];
    lit(a, "{\"kind\":"); string(a, kind); lit(a, ",\"payload\":"); put(a, buffers[0].bytes, buffers[0].size);
    lit(a, ",\"schemaVersion\":"); string(a, schema); lit(a, ",\"sequence\":"); number(a, seq); lit(a, "}");
    input = PyBytes_FromStringAndSize(a->bytes, a->size); if (!input) goto done_output;
    hash = PyObject_CallOneArg(f->sha256, input); if (!hash) goto done_output;
    digest = PyObject_CallMethod(hash, "hexdigest", NULL); if (!digest) goto done_output;
    if (!ascii_text(digest) || PyUnicode_GET_LENGTH(digest) != 64) { PyErr_SetString(PyExc_ValueError, "invalid SHA256 result"); goto done_output; }
    full_hash = PyUnicode_FromFormat("sha256:%U", digest); if (!full_hash) goto done_output;
    lit(b, "{\"kind\":"); string(b, kind); lit(b, ",\"outputHash\":"); string(b, full_hash);
    lit(b, ",\"payload\":"); put(b, buffers[0].bytes, buffers[0].size);
    lit(b, ",\"schemaVersion\":"); string(b, schema); lit(b, ",\"sequence\":"); number(b, seq); lit(b, "}");
    if (!a->ok || !b->ok) goto fallback_output;
    encoded = PyBytes_FromStringAndSize(b->bytes, b->size); if (!encoded) goto done_output;
    if (!host_parts) { result = PyTuple_Pack(2, full_hash, encoded); goto done_output; }
    /* Receipt is sealed before host-only aliases are inserted. The copied
     * payload is detached from the author's object, as in _to_host_output. */
    int target = PyUnicode_CompareWithASCIIString(kind, "TARGET_POSITION") == 0;
    int order = PyUnicode_CompareWithASCIIString(kind, "ORDER_INTENT") == 0;
    PyObject *quantity = PyDict_GetItemString(payload, "quantity");
    if (quantity && (target || order)) {
        const char *alias = target ? "targetExposure" : "qty";
        if (!PyDict_GetItemString(payload, alias) && PyDict_SetItemString(payload, alias, quantity) < 0) goto done_output;
    }
    if (target && quantity && PyDict_Size(payload) == 2 &&
        PyObject_RichCompareBool(quantity, PyDict_GetItemString(payload, "targetExposure"), Py_EQ) == 1) {
        state_hash = PyObject_CallOneArg(args[4], quantity);
    } else {
        buffers[0].size = 0; buffers[0].ok = 1;
        if (flat_dict(&buffers[0], payload) != 1) goto done_output;
        Py_CLEAR(input); Py_CLEAR(hash); Py_CLEAR(digest);
        input = PyBytes_FromStringAndSize(buffers[0].bytes, buffers[0].size); if (!input) goto done_output;
        hash = PyObject_CallOneArg(f->sha256, input); if (!hash) goto done_output;
        digest = PyObject_CallMethod(hash, "hexdigest", NULL); if (!digest) goto done_output;
        state_hash = PyUnicode_FromFormat("sha256:%U", digest);
    }
    if (!state_hash) goto done_output;
    host_args = PyTuple_Pack(5, sequence, kind, payload, state_hash, full_hash); if (!host_args) goto done_output;
    result = PyTuple_Pack(2, host_args, encoded); goto done_output;
fallback_output:
    if (!PyErr_Occurred()) result = Py_NewRef(Py_None);
done_output:
    PyMem_Free(buffers); Py_XDECREF(payload); Py_XDECREF(input); Py_XDECREF(hash); Py_XDECREF(digest);
    Py_XDECREF(full_hash); Py_XDECREF(encoded); Py_XDECREF(state_hash); Py_XDECREF(host_args); return result;
}
static PyObject *output_wire(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    return encode_output(f, args, nargs, 0);
}
static PyObject *output_parts(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    return encode_output(f, args, nargs, 1);
}
#include "executor.c"

static PyObject *event_wire_size(PyObject *module, PyObject *const *args, Py_ssize_t nargs) {
    long long seq, stamp; PyObject *payload = NULL, *result = NULL; Buffer *b = NULL;
    if (nargs != 4) { PyErr_SetString(PyExc_TypeError, "event_wire_size requires payload, sequence, time, role"); return NULL; }
    if (!PyDict_CheckExact(args[0]) || PyDict_Size(args[0]) > 32 || !safe_int(args[1], &seq) ||
        !safe_int(args[2], &stamp) || !ascii_text(args[3])) goto size_fallback;
    payload = PyDict_Copy(args[0]); if (!payload) goto size_done;
    b = PyMem_Malloc(sizeof(Buffer)); if (!b) { PyErr_NoMemory(); goto size_done; }
    b->size=0; b->ok=1;
    lit(b, "{\"event_time_ms\":"); number(b, stamp); lit(b, ",\"payload\":");
    int accepted = flat_dict(b, payload);
    if (accepted < 0) goto size_done;
    if (!accepted) goto size_fallback;
    lit(b, ",\"role\":"); string(b, args[3]); lit(b, ",\"sequence\":"); number(b, seq); lit(b, "}");
    if (!b->ok) goto size_fallback;
    result = PyLong_FromSsize_t(b->size); goto size_done;
size_fallback:
    if (!PyErr_Occurred()) result = Py_NewRef(Py_None);
size_done:
    PyMem_Free(b); Py_XDECREF(payload); return result;
}
static PyMethodDef factory_methods[] = {
    {"bind_outputs", (PyCFunction)bind_outputs, METH_FASTCALL, "Bind qualified SDK output layouts."},
    {"object_output", (PyCFunction)object_output, METH_FASTCALL, "Read standard output slots or defer."},
    {"execute", (PyCFunction)execute_observation, METH_FASTCALL, "Sequential native observation/callback/receipt entry."},
    {"build", (PyCFunction)build_row, METH_FASTCALL, "Build one current SDK observation and exact canonical receipt bytes."},
    {"stats", (PyCFunction)factory_stats, METH_NOARGS, "Return this factory's row counts."},
    {"output_wire", (PyCFunction)output_wire, METH_FASTCALL, "Encode a qualified V1 output without changing its hash."},
    {"output_parts", (PyCFunction)output_parts, METH_FASTCALL, "Seal output bytes and prepare detached host constructor arguments."},
    {"bind_transcript", (PyCFunction)bind_transcript, METH_O, "Bind the existing V1 streaming hash once."},
    {"record_v1", (PyCFunction)record_v1, METH_FASTCALL, "Record exact V1 bytes with one bounded allocation."},
    {"record_success", (PyCFunction)record_success, METH_FASTCALL, "Record successful V1 result bytes without an intermediate response allocation."},
    {NULL}
};
static PyType_Slot factory_slots[] = {
    {Py_tp_new, PyType_GenericNew}, {Py_tp_init, initialize_factory}, {Py_tp_dealloc, destroy_factory},
    {Py_tp_traverse, visit_factory}, {Py_tp_clear, clear_factory}, {Py_tp_methods, factory_methods}, {0, NULL}
};
static PyType_Spec factory_spec = {"app.backtest.strategy._native_rows.RowFactory", sizeof(Factory), 0,
                                 Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC, factory_slots};
static PyMethodDef module_methods[] = {
    {"empty_decision_hash", (PyCFunction)empty_decision_hash, METH_FASTCALL, "Hash an exact empty decision or defer unsupported clock/string shapes."},
    {"event_wire_size", (PyCFunction)event_wire_size, METH_FASTCALL, "Count exact canonical event bytes, or defer."}, {NULL}
};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_native_rows", "Optional exact row construction for V1 Python scripts.", 0, module_methods};
PyMODINIT_FUNC PyInit__native_rows(void) {
    PyObject *m = PyModule_Create(&module); if (!m) return NULL;
    PyObject *type = PyType_FromSpec(&factory_spec); if (!type) { Py_DECREF(m); return NULL; }
    if (PyModule_AddObject(m, "RowFactory", type) < 0) { Py_DECREF(type); Py_DECREF(m); return NULL; }
    if (PyModule_AddIntConstant(m, "ROW_PROTOCOL_ABI", 1) < 0) { Py_DECREF(m); return NULL; }
    return m;
}
