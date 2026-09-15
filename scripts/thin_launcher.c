/* One-shot macOS launcher for Sentinel's live Lab checkout.

   Launch Services starts this compiled executable.  The parent returns at once
   while a detached child replaces itself with the project's Python process.
   There is no persistent launchd job and therefore no restart-on-exit policy.
*/

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define LOG_PATH "/tmp/sentinel-launch.log"

static void write_error(const char *message) {
    int fd = open(LOG_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        dprintf(fd, "Sentinel cannot start: %s\n", message);
        close(fd);
    }
}

static int bundle_resource_path(char *output, size_t capacity) {
    char executable[PATH_MAX];
    uint32_t size = (uint32_t)sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0) {
        return -1;
    }

    char resolved[PATH_MAX];
    if (realpath(executable, resolved) == NULL) {
        return -1;
    }

    char *macos = strrchr(resolved, '/');
    if (macos == NULL) {
        return -1;
    }
    *macos = '\0';
    char *contents = strrchr(resolved, '/');
    if (contents == NULL) {
        return -1;
    }
    *contents = '\0';

    int written = snprintf(
        output, capacity, "%s/Resources/project_root.txt", resolved
    );
    return (written > 0 && (size_t)written < capacity) ? 0 : -1;
}

static int read_project_root(char *output, size_t capacity) {
    char config_path[PATH_MAX];
    if (bundle_resource_path(config_path, sizeof(config_path)) != 0) {
        return -1;
    }

    FILE *config = fopen(config_path, "r");
    if (config == NULL) {
        return -1;
    }
    char *result = fgets(output, (int)capacity, config);
    fclose(config);
    if (result == NULL) {
        return -1;
    }
    output[strcspn(output, "\r\n")] = '\0';
    return output[0] == '\0' ? -1 : 0;
}

int main(void) {
    char project_root[PATH_MAX];
    char python_bin[PATH_MAX];
    char main_py[PATH_MAX];

    if (read_project_root(project_root, sizeof(project_root)) != 0) {
        write_error("the bundled project path is missing or unreadable");
        return 1;
    }
    if (snprintf(python_bin, sizeof(python_bin), "%s/.venv/bin/python", project_root)
            >= (int)sizeof(python_bin)
        || snprintf(main_py, sizeof(main_py), "%s/main.py", project_root)
            >= (int)sizeof(main_py)) {
        write_error("the project path is too long");
        return 1;
    }
    if (access(python_bin, X_OK) != 0 || access(main_py, R_OK) != 0) {
        write_error("the Lab checkout or its Python environment is missing");
        return 1;
    }

    pid_t child = fork();
    if (child < 0) {
        write_error(strerror(errno));
        return 1;
    }
    if (child > 0) {
        return 0;
    }

    if (setsid() < 0 || chdir(project_root) != 0) {
        write_error(strerror(errno));
        _exit(1);
    }

    int log_fd = open(LOG_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    int null_fd = open("/dev/null", O_RDONLY);
    if (log_fd >= 0) {
        dup2(log_fd, STDOUT_FILENO);
        dup2(log_fd, STDERR_FILENO);
    }
    if (null_fd >= 0) {
        dup2(null_fd, STDIN_FILENO);
    }
    long max_fd = sysconf(_SC_OPEN_MAX);
    if (max_fd < 0 || max_fd > 65536) {
        max_fd = 1024;
    }
    for (int fd = 3; fd < max_fd; ++fd) {
        close(fd);
    }

    execl(python_bin, python_bin, main_py, (char *)NULL);
    write_error(strerror(errno));
    _exit(127);
}
