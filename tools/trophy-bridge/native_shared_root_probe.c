/* PS5 per-game shared RPCS3 data access probe — NO WRITES.
 *
 * Build-only prototype. For later *explicitly authorised* temporary title tests:
 *   1. Boot under a distinct OWNER TEST PPSA title.
 *   2. Validate exact owner marker under the title's /app0.
 *   3. Check only path visibility/readability in the running title sandbox:
 *      - existing shared RPCS3 data root /data/homebrew/PPSA99303/rpcs3
 *      - PS3 dev_hdd0 directory (not private trophy files)
 *      - app0 mirror/helper paths, which a full emulator would need.
 *   4. Log status codes (not directory listings, file content or private IDs).
 *   5. Exit normally after 20 seconds.
 *
 * Does NOT register trophies, call PSN, modify configs/saves, mount anything,
 * create symlinks, open a network socket or launch the emulator.
 * SPDX-License-Identifier: MIT
 */
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int sceKernelDebugOutText(int channel, const char *text);
int sceKernelUsleep(unsigned microseconds);
int sceSystemServiceLoadExec(const char *path, const char *const *argv);

#define OWNER_ID "PPSA88395"
#define OWNER_MARKER "PPSA88395 NPWR00132_00 NPUB30702"
#define SHARED_ROOT "/data/homebrew/PPSA99303/rpcs3"

void catchReturnFromMain(int status)
{
    (void)status;
    sceSystemServiceLoadExec("exit", NULL);
    for (;;)
        sceKernelUsleep(100000);
}

static void log_status(const char *key, int ok, int error)
{
    char line[192];
    snprintf(line, sizeof(line),
             "[KB SHARED-ROOT] %s: %s (errno=%d)\n",
             key, ok ? "yes" : "no", ok ? 0 : error);
    sceKernelDebugOutText(0, line);
}

static int check_dir(const char *key, const char *path)
{
    struct stat st;
    errno = 0;
    if (stat(path, &st) != 0)
    {
        log_status(key, 0, errno);
        return 0;
    }
    if (!S_ISDIR(st.st_mode))
    {
        log_status(key, 0, ENOTDIR);
        return 0;
    }
    errno = 0;
    DIR *dir = opendir(path);
    if (!dir)
    {
        log_status(key, 0, errno);
        return 0;
    }
    closedir(dir);
    log_status(key, 1, 0);
    return 1;
}

static void check_file(const char *key, const char *path)
{
    struct stat st;
    errno = 0;
    if (stat(path, &st) != 0)
    {
        log_status(key, 0, errno);
        return;
    }
    log_status(key, S_ISREG(st.st_mode), S_ISREG(st.st_mode) ? 0 : EINVAL);
}

static int validate_owner(void)
{
    char marker[sizeof(OWNER_MARKER) + 4] = {0};
    FILE *in = fopen("/app0/native-owner.txt", "rb");
    if (!in)
        return 0;
    size_t n = fread(marker, 1, sizeof(marker) - 1, in);
    fclose(in);
    marker[n] = '\0';
    marker[strcspn(marker, "\r\n")] = '\0';
    return strcmp(marker, OWNER_MARKER) == 0;
}

int main(void)
{
    if (!validate_owner())
    {
        sceKernelDebugOutText(0, "[KB SHARED-ROOT] owner ID marker mismatch, ending\n");
        return 1;
    }

    sceKernelDebugOutText(0, "[KB SHARED-ROOT] owner title=" OWNER_ID
                             " audit starting; no data writes\n");
    const int data = check_dir("shared_data_root",
                               SHARED_ROOT);
    const int dev = check_dir("shared_dev_hdd0",
                              SHARED_ROOT "/dev_hdd0");
    const int app_data = check_dir("local_app0_rpcs3",
                                   "/app0/rpcs3");
    check_file("local_eboot",
               "/app0/eboot.bin");
    check_file("local_text_mirror",
               "/app0/rpcs3ps5-text.bin");
    check_file("local_iohelper",
               "/app0/rpcs3ps5-io.elf");

    if (data && dev)
        sceKernelDebugOutText(0, "[KB SHARED-ROOT] shared data visible in THIS title sandbox\n");
    else
        sceKernelDebugOutText(0, "[KB SHARED-ROOT] shared data NOT proven accessible; do not migrate\n");
    if (!app_data)
        sceKernelDebugOutText(0, "[KB SHARED-ROOT] no local /app0/rpcs3 mapping; full emulator blocked\n");

    for (unsigned i = 0; i < 20; ++i)
        sceKernelUsleep(1000000);
    sceKernelDebugOutText(0, "[KB SHARED-ROOT] normal exit; no PS5 changes\n");
    return 0;
}
