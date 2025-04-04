#define PY_SSIZE_T_CLEAN
#define PY_LIMITED_API 0x030b00f0
#include <Python.h>
#include <unicodeobject.h>

#include <checkdynlib.h>


static PyObject *
checkdynlib_impl(PyObject *self, PyObject *args)
{
    int a, b;
    if (!PyArg_ParseTuple(args, "i|i:checkdynlib", &a, &b)) {
        return NULL;
    }

    int result = sum(a, b); /* checkdynlib provides "sum" */

    return PyLong_FromLong(result);
}


static PyMethodDef dynlib_consumer_methods[] = {
    {"checkdynlib_sum", checkdynlib_impl, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL} /* sentinel */
};


static struct PyModuleDef dynlib_consumer_module = {
    PyModuleDef_HEAD_INIT,
    "dynlib_consumer", /* m_name */
    NULL, /* m_doc */
    -1, /* m_size */
    dynlib_consumer_methods, /* m_methods */
};


PyMODINIT_FUNC
PyInit_dynlib_consumer(void)
{
    return PyModule_Create(&dynlib_consumer_module);
}
