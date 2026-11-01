/*
 * KB-RPCS3 PS5 trophy-bridge: read-only system firmware query.
 *
 * Runs only sysctlbyname() on kern.sdk_version / kern.version. No process
 * patches, privileged writes, app launches, game alterations, or trophy APIs.
 * Result is printed to the payload loader's captured stdout.
 * SPDX-License-Identifier: MIT
 */
#include <stdint.h>
#include <stdio.h>
#include <sys/sysctl.h>

int main(void)
{
    uint32_t sdk = 0;
    size_t sdk_size = sizeof(sdk);
    const int result = sysctlbyname("kern.sdk_version", &sdk, &sdk_size, NULL, 0);
    printf("trophy-fw-probe: START\n");
    if (result == 0 && sdk_size == sizeof(sdk))
    {
        printf("trophy-fw-probe: sdk=0x%08x\n", (unsigned)sdk);
        printf("trophy-fw-probe: sdk_version_bcd=%02x.%02x\n",
               (unsigned)((sdk >> 24) & 0xff), (unsigned)((sdk >> 16) & 0xff));
    }
    else
    {
        printf("trophy-fw-probe: sdk_unavailable result=%d size=%zu\n",
               result, sdk_size);
    }
    char version[512] = {0};
    size_t len = sizeof(version) - 1;
    if (sysctlbyname("kern.version", version, &len, NULL, 0) == 0)
    {
        if (len >= sizeof(version)) len = sizeof(version) - 1;
        version[len] = '\0';
        // Deliberately print only the first line, which includes build revision.
        for (size_t i = 0; i < len; ++i)
            if (version[i] == '\r' || version[i] == '\n') { version[i] = '\0'; break; }
        printf("trophy-fw-probe: kernel_build=%s\n", version);
    }
    else
    {
        printf("trophy-fw-probe: kernel_build_unavailable\n");
    }
    puts("trophy-fw-probe: DONE");
    fflush(stdout);
    return result == 0 ? 0 : 1;
}
