/* Included by rows.c: shares its bounded encoders and owned Factory references. */
static PyObject *bind_outputs(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs != 3 || !PyTuple_CheckExact(args[2]) || PyTuple_GET_SIZE(args[2]) != 3) {
        PyErr_SetString(PyExc_TypeError, "invalid output binding"); return NULL;
    }
    if (f->output_specs) { PyErr_SetString(PyExc_ValueError, "outputs already bound"); return NULL; }
    PyObject *specs = PyTuple_New(3); if (!specs) return NULL;
    for (int i=0; i<3; ++i) {
        PyObject *spec = PyTuple_GET_ITEM(args[2], i);
        if (!PyTuple_CheckExact(spec) || PyTuple_GET_SIZE(spec) != 6 ||
            !PyType_Check(PyTuple_GET_ITEM(spec,0)) || !PyCallable_Check(PyTuple_GET_ITEM(spec,1)) ||
            !PyTuple_CheckExact(PyTuple_GET_ITEM(spec,2)) || !PyTuple_CheckExact(PyTuple_GET_ITEM(spec,3)) ||
            !ascii_text(PyTuple_GET_ITEM(spec,4)) || !ascii_text(PyTuple_GET_ITEM(spec,5))) goto invalid;
        PyObject *names=PyTuple_GET_ITEM(spec,2), *wire=PyTuple_GET_ITEM(spec,3);
        if (PyTuple_GET_SIZE(names) != (i==0 ? 4 : i==1 ? 1 : 7) || PyTuple_GET_SIZE(wire)!=PyTuple_GET_SIZE(names)) goto invalid;
        for (Py_ssize_t j=0; j<PyTuple_GET_SIZE(names); ++j)
            if (!ascii_text(PyTuple_GET_ITEM(names,j)) || !ascii_text(PyTuple_GET_ITEM(wire,j))) goto invalid;
        PyObject *slots = capture_slots(PyTuple_GET_ITEM(spec,0), names);
        if (!slots) { Py_DECREF(specs); return NULL; }
        PyObject *bound = PyTuple_Pack(7, PyTuple_GET_ITEM(spec,0), PyTuple_GET_ITEM(spec,1), names, wire,
                                    PyTuple_GET_ITEM(spec,4), PyTuple_GET_ITEM(spec,5), slots);
        Py_DECREF(slots); if (!bound) { Py_DECREF(specs); return NULL; }
        PyTuple_SET_ITEM(specs, i, bound);
    }
    f->output_models=Py_NewRef(args[0]); f->output_kind=Py_NewRef(args[1]); f->output_specs=specs;
    Py_RETURN_NONE;
invalid:
    Py_DECREF(specs); PyErr_SetString(PyExc_ValueError, "unsupported output layout"); return NULL;
}

static PyObject *object_output(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs!=3) { PyErr_SetString(PyExc_TypeError, "object_output requires sequence, output, target hash"); return NULL; }
    if (!f->output_specs) Py_RETURN_NONE;
    PyObject *current=PyObject_GetAttrString(f->output_models,"output_kind");
    if (!current) return NULL;
    int unchanged=current==f->output_kind; Py_DECREF(current);
    if (!unchanged) Py_RETURN_NONE;
    for (int i=0; i<3; ++i) {
        PyObject *spec=PyTuple_GET_ITEM(f->output_specs,i), *type=PyTuple_GET_ITEM(spec,0);
        if ((PyObject *)Py_TYPE(args[1])!=type) continue;
        current=PyObject_GetAttr(f->output_models,PyTuple_GET_ITEM(spec,5)); if (!current) return NULL;
        unchanged=current==type; Py_DECREF(current); if (!unchanged) Py_RETURN_NONE;
        current=PyObject_GetAttrString(type,"to_payload"); if (!current) return NULL;
        unchanged=current==PyTuple_GET_ITEM(spec,1); Py_DECREF(current); if (!unchanged) Py_RETURN_NONE;
        PyObject *names=PyTuple_GET_ITEM(spec,2), *wire_names=PyTuple_GET_ITEM(spec,3);
        if (!slots_unchanged(type,names,PyTuple_GET_ITEM(spec,6))) Py_RETURN_NONE;
        PyObject *payload=PyDict_New(); if (!payload) return NULL;
        for (Py_ssize_t j=0; j<PyTuple_GET_SIZE(names); ++j) {
            PyObject *value=PyObject_GetAttr(args[1],PyTuple_GET_ITEM(names,j));
            if (!value) { Py_DECREF(payload); return NULL; }
            int optional=i==2 && (j==3 || j==4);
            if (optional && value==Py_None) { Py_DECREF(value); continue; }
            if (!ascii_text(value) || memchr(PyUnicode_1BYTE_DATA(value),127,(size_t)PyUnicode_GET_LENGTH(value))) {
                Py_DECREF(value); Py_DECREF(payload); Py_RETURN_NONE;
            }
            if (i==2 && j==6 && PyUnicode_GET_LENGTH(value)==0) { Py_DECREF(value); continue; }
            int status=PyDict_SetItem(payload,PyTuple_GET_ITEM(wire_names,j),value);
            Py_DECREF(value); if (status<0) { Py_DECREF(payload); return NULL; }
        }
        PyObject *schema=PyObject_GetAttrString(f->output_models,"OUTPUT_SCHEMA");
        if (!schema) { Py_DECREF(payload); return NULL; }
        PyObject *values[]={args[0],PyTuple_GET_ITEM(spec,4),payload,schema,args[2]};
        PyObject *result=encode_output(f,values,5,1); Py_DECREF(schema); Py_DECREF(payload); return result;
    }
    Py_RETURN_NONE;
}

static PyObject *execute_observation(Factory *f, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs!=7 || (args[6]!=Py_True && args[6]!=Py_False)) {
        PyErr_SetString(PyExc_TypeError,"execute requires row, clocks, phase, runner, session, output mode"); return NULL;
    }
    PyObject *runner=args[4], *session=args[5], *prepared=NULL, *method=NULL, *strategy=NULL, *output=NULL;
    PyObject *count=NULL, *bound=NULL, *request_id=NULL, *chain=NULL, *encoded=NULL, *parts=NULL, *host=NULL, *result=NULL;
    PyObject *call_result=NULL, *target_hash=NULL, *exception=NULL, *new_count=NULL, *host_type=NULL;
    int warmup=PyUnicode_Check(args[3]) && PyUnicode_CompareWithASCIIString(args[3],"WARMUP")==0;
    prepared=build_row(f,args,4); if (!prepared || prepared==Py_None) return prepared;
    PyObject *observation=PyTuple_GET_ITEM(prepared,0), *wire=PyTuple_GET_ITEM(prepared,1);
    PyObject *run_id=PyObject_GetAttrString(session,"run_id"); if (!run_id) goto done;
    call_result=PyObject_CallMethod(session,"_accept_clock","OOOO",run_id,args[1],args[2],args[2]);
    Py_DECREF(run_id); if (!call_result) goto done; Py_CLEAR(call_result);
    count=PyObject_GetAttrString(runner,"_count"); bound=PyObject_GetAttrString(runner,"_bound");
    if (!count || !bound) goto done;
    long long ordinal;
    if (!safe_int(count,&ordinal) || ordinal<0 || ordinal>=SAFE_INT) {
        PyErr_SetString(PyExc_ValueError,"invalid native request ordinal"); goto done;
    }
    int is_bound=PyObject_IsTrue(bound); if (is_bound<0) goto done;
    request_id=PyLong_FromLongLong(is_bound ? (ordinal<1 ? ordinal+1 : 2) : ordinal+1); if (!request_id) goto done;
    strategy=PyObject_GetAttrString(runner,"_strategy"); if (!strategy) goto user_error;
    method=PyObject_GetAttrString(strategy,warmup?"warmup":"step"); if (!method) goto user_error;
    output=PyObject_CallOneArg(method,observation); if (!output) goto user_error;
    if (warmup || output==Py_None) {
        encoded=PyBytes_FromString("null"); if (!encoded) goto done;
    } else {
        if (args[6]==Py_True) {
            target_hash=PyObject_GetAttrString(runner,"_native_target_hash"); if (!target_hash) goto user_error;
            /* Scripts may change even a frozen observation via object.__setattr__;
             * preserve the existing post-callback output sequence behavior. */
            PyObject *sequence=PyObject_GetAttrString(observation,"sequence"); if (!sequence) goto user_error;
            PyObject *values[]={sequence,output,target_hash}; parts=object_output(f,values,3); Py_DECREF(sequence);
            if (!parts) goto user_error;
        }
        if (!parts || parts==Py_None) goto python_finish;
        encoded=Py_NewRef(PyTuple_GET_ITEM(parts,1));
    }
    chain=is_bound ? PyObject_GetAttrString(runner,"_chain") : Py_NewRef(Py_None); if (!chain) goto done;
    PyObject *record_args[]={request_id,warmup?Py_True:Py_False,wire,encoded,chain};
    call_result=record_impl(f,record_args,5,1); if (!call_result) goto done;
    if (is_bound && PyObject_SetAttrString(runner,"_chain",call_result)<0) goto done;
    new_count=PyNumber_Add(count,f->one); if (!new_count || PyObject_SetAttrString(runner,"_count",new_count)<0) goto done;
    if (parts && parts!=Py_None) {
        host_type=PyObject_GetAttrString(runner,"_native_output_type"); if (!host_type) goto done;
        host=PyObject_CallObject(host_type,PyTuple_GET_ITEM(parts,0)); if (!host) goto done;
    } else host=Py_NewRef(Py_None);
    goto success;
user_error:
    if (!PyErr_ExceptionMatches(PyExc_Exception)) goto done;
    {
        PyObject *type=NULL,*traceback=NULL;
        PyErr_Fetch(&type,&exception,&traceback); PyErr_NormalizeException(&type,&exception,&traceback);
        if (exception && traceback) PyException_SetTraceback(exception,traceback);
        Py_XDECREF(type); Py_XDECREF(traceback);
        if (!exception) goto done;
    }
python_finish:
    host=PyObject_CallMethod(runner,"_complete_native","OOOOO",prepared,warmup?Py_True:Py_False,
                             output?output:Py_None,exception?exception:Py_None,(PyObject *)f);
    if (!host) goto done;
success:
    result=PyTuple_Pack(1,host);
done:
    Py_XDECREF(prepared); Py_XDECREF(method); Py_XDECREF(strategy); Py_XDECREF(output);
    Py_XDECREF(count); Py_XDECREF(bound); Py_XDECREF(request_id); Py_XDECREF(chain); Py_XDECREF(encoded);
    Py_XDECREF(parts); Py_XDECREF(host); Py_XDECREF(call_result); Py_XDECREF(target_hash); Py_XDECREF(exception);
    Py_XDECREF(new_count); Py_XDECREF(host_type); return result;
}
