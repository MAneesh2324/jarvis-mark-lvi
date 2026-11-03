#include <Python.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#if !defined(VENV_PYTHON) || !defined(MAIN_SCRIPT) || !defined(PROJECT_ROOT) || !defined(STARTUP_LOG)
#error "Build with native/build_launcher.py to configure local installation paths"
#endif
int main(int argc, char **argv) {
    setenv("JARVIS_NATIVE_APP", "1", 1);
    if (argc == 1) {
        if (chdir(PROJECT_ROOT) != 0) return 1;
        int fd = open(STARTUP_LOG, O_WRONLY | O_CREAT | O_APPEND, 0600);
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
