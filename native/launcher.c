#include <Python.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#define VENV_PYTHON "/Users/maneesh/Desktop/Mark-LVI/.venv/bin/python"
#define MAIN_SCRIPT "/Users/maneesh/Desktop/Mark-LVI/main.py"
int main(int argc, char **argv) {
    setenv("JARVIS_NATIVE_APP", "1", 1);
    if (argc == 1) {
        if (chdir("/Users/maneesh/Desktop/Mark-LVI") != 0) return 1;
        int fd = open("/Users/maneesh/Desktop/Mark-LVI/native-startup.log", O_WRONLY | O_CREAT | O_APPEND, 0600);
        if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); close(fd); }
        setvbuf(stdout, NULL, _IOLBF, 0);
        setvbuf(stderr, NULL, _IOLBF, 0);
    }
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    PyStatus status = PyConfig_SetBytesString(&config, &config.program_name, VENV_PYTHON);
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesString(&config, &config.executable, VENV_PYTHON);
    char *default_argv[] = {VENV_PYTHON, MAIN_SCRIPT};
    if (!PyStatus_Exception(status)) {
        if (argc == 1) status = PyConfig_SetBytesArgv(&config, 2, default_argv);
        else { argv[0] = VENV_PYTHON; status = PyConfig_SetBytesArgv(&config, argc, argv); }
    }
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    return Py_RunMain();
}
