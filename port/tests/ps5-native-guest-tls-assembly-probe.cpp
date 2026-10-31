// PS5-target-only feasibility probe; NOT linked into RPCS3/game runtime.
// Compare native TLS vs the direct guest-context and local-store pointers
// currently supplied as JIT function arguments.
#include <stdint.h>
struct guest_state {
    uint64_t gpr[32];
    unsigned char* ls;
};
extern "C" {
__attribute__((visibility("hidden"))) thread_local guest_state* ps5_current_guest = nullptr;
__attribute__((noinline)) void ps5_bind_guest(guest_state* guest) {
    ps5_current_guest = guest;
}
__attribute__((noinline)) void ps5_clear_guest() {
    ps5_current_guest = nullptr;
}
__attribute__((noinline)) uint64_t ps5_tls_r13() {
    const guest_state* guest = ps5_current_guest;
    return guest ? guest->gpr[13] : 0;
}
__attribute__((noinline)) uint64_t ps5_direct_r13(const guest_state* guest) {
    return guest->gpr[13];
}
__attribute__((noinline)) unsigned char ps5_tls_ls_byte(unsigned offset) {
    const guest_state* guest = ps5_current_guest;
    return guest ? guest->ls[offset & 0x3ffffu] : 0;
}
__attribute__((noinline)) unsigned char ps5_direct_ls_byte(const unsigned char* ls, unsigned offset) {
    return ls[offset & 0x3ffffu];
}
}
