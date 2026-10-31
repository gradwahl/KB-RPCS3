// PS5 Section 5: TLS template / alignment / initializers / object lifetime.
#include <cstddef>
#include <cstdint>
alignas(32) thread_local unsigned char ps5_native_tls_pattern[96] = {0x31,0x72,0x59,0xA5};
extern "C" __attribute__((noinline))
unsigned ps5_tls_pattern_read()
{
    return static_cast<unsigned>(ps5_native_tls_pattern[0]) +
           static_cast<unsigned>(ps5_native_tls_pattern[1]) +
           static_cast<unsigned>(ps5_native_tls_pattern[3]);
}
#ifdef PS5_HOST_TLS_LIFECYCLE_TEST
#include <atomic>
#include <cassert>
#include <thread>
#include <vector>
static std::atomic<unsigned> constructed{0}, destroyed{0};
struct state {
    int value;
    state() : value(791) { constructed.fetch_add(1); }
    ~state() { destroyed.fetch_add(1); }
};
static thread_local state tls_lifecycle;
int main() {
    assert(ps5_tls_pattern_read()==(0x31+0x72+0xA5));
    assert(reinterpret_cast<std::uintptr_t>(ps5_native_tls_pattern)%32==0);
    tls_lifecycle.value=42;
    std::vector<std::thread> workers;
    for(int i=0;i<4;++i) {
        workers.emplace_back([i] {
            assert(ps5_native_tls_pattern[0]==0x31);
            assert(ps5_native_tls_pattern[1]==0x72);
            assert(reinterpret_cast<std::uintptr_t>(ps5_native_tls_pattern)%32==0);
            ps5_native_tls_pattern[0]=static_cast<unsigned char>(i+1);
            assert(tls_lifecycle.value==791);
            tls_lifecycle.value=i+100;
        });
    }
    for(auto& worker:workers)worker.join();
    assert(ps5_native_tls_pattern[0]==0x31);
    assert(tls_lifecycle.value==42);
    assert(constructed.load()==5);
    assert(destroyed.load()==4); // Main thread lifetime has not ended
}
#endif
