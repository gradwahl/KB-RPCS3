// Host functional test for the PS5-target guest-context TLS prototype.
// Builds/runs on Linux only; PS5 assembly is separately cross-compiled.
#include <atomic>
#include <cassert>
#include <thread>
#include "ps5-native-guest-tls-assembly-probe.cpp"

int main()
{
    guest_state a{}, b{};
    unsigned char a_ls[256 * 1024]{}, b_ls[256 * 1024]{};
    a.gpr[13] = 0x1111111111111111ull;
    b.gpr[13] = 0x2222222222222222ull;
    a.ls = a_ls;
    b.ls = b_ls;
    a_ls[9] = 12;
    b_ls[9] = 34;

    // Unbound state must never point at stale guest memory.
    assert(ps5_tls_r13() == 0 && ps5_tls_ls_byte(9) == 0);
    ps5_bind_guest(&a);
    assert(ps5_tls_r13() == ps5_direct_r13(&a));
    assert(ps5_tls_ls_byte(9) == ps5_direct_ls_byte(a.ls, 9));

    // Simulate switching guest contexts on a single host thread.
    ps5_bind_guest(&b);
    assert(ps5_tls_r13() == ps5_direct_r13(&b));
    assert(ps5_tls_ls_byte(9) == ps5_direct_ls_byte(b.ls, 9));

    std::atomic<bool> child_ready{false}, child_done{false};
    std::thread worker([&] {
        assert(ps5_tls_r13() == 0); // A new host thread must start unbound.
        ps5_bind_guest(&a);
        child_ready.store(true, std::memory_order_release);
        while (!child_done.load(std::memory_order_acquire)) {}
        assert(ps5_tls_r13() == a.gpr[13]);
        assert(ps5_tls_ls_byte(9) == 12);
        ps5_clear_guest();
        assert(ps5_tls_r13() == 0);
    });
    while (!child_ready.load(std::memory_order_acquire)) {}
    // Simultaneously bound guest states on different host threads.
    assert(ps5_tls_r13() == b.gpr[13]);
    assert(ps5_tls_ls_byte(9) == 34);
    child_done.store(true, std::memory_order_release);
    worker.join();

    ps5_clear_guest();
    assert(ps5_tls_r13() == 0 && ps5_tls_ls_byte(9) == 0);
    // The real RPCS3 hot paths already pass these pointers directly.
    assert(ps5_direct_r13(&a) == a.gpr[13]);
    assert(ps5_direct_ls_byte(b.ls, 9) == 34);
}
