/* PS5 native trophy owner: SAFE TITLE-LIFETIME PROBE ONLY.
 *
 * This deliberately does NOT launch RPCS3, call PS5 trophy APIs, read
 * account data, access the network, patch a process, or write files.
 * Each separate PPSA8xxxx title can run this process for 20 seconds
 * and report its own installed title-ID plan from /app0/native-owner.txt.
 *
 * Not evidence that Sony's trophy daemon will register an NPWR.
 * SPDX-License-Identifier: MIT
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int sceKernelDebugOutText(int channel, const char *text);
int sceKernelUsleep(unsigned microseconds);
int sceSystemServiceLoadExec(const char *path, const char *const *argv);

void catchReturnFromMain(int status)
{
    (void)status;
    sceSystemServiceLoadExec("exit", NULL);
    for (;;)
        sceKernelUsleep(100000);
}

static int valid_line(const char *text)
{
    /* Untrusted text is only logged; reject paths, controls and punctuation. */
    const size_t n = strlen(text);
    if (n < 15 || n > 65)
        return 0;
    for (size_t i = 0; i < n; i++)
    {
        char c = text[i];
        if (!((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
              c == ' ' || c == '_'))
            return 0;
    }
    return 1;
}

int main(void)
{
    char identity[96] = {0};
    FILE *file = fopen("/app0/native-owner.txt", "rb");
    if (file)
    {
        size_t len = fread(identity, 1, sizeof(identity) - 1, file);
        fclose(file);
        identity[len] = '\0';
        identity[strcspn(identity, "\r\n")] = 0;
    }

    if (!valid_line(identity))
    {
        sceKernelDebugOutText(0, "[KB Trophy Owner] Missing/invalid native-owner.txt - probe ending\n");
        return 1;
    }
    char line[200];
    snprintf(line, sizeof(line), "[KB Trophy Owner] Native-title lifecycle probe: %s\n", identity);
    sceKernelDebugOutText(0, line);
    for (unsigned second = 0; second < 20; second++)
    {
        if (second % 5 == 0)
            sceKernelDebugOutText(0, "[KB Trophy Owner] alive (no trophy APIs, no console writes)\n");
        sceKernelUsleep(1000000);
    }
    sceKernelDebugOutText(0, "[KB Trophy Owner] probe finished; requesting normal title exit\n");
    return 0;
}
