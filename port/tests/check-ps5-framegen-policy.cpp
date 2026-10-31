// SPDX-License-Identifier: MIT
#include "framegen_policy.h"
#include <cassert>
int main()
{
    using ps5_framegen::should_generate;
    assert(!should_generate(false, 33'333'333, 60'000));
    assert(should_generate(true, 33'333'333, 60'000));
    assert(!should_generate(true, 16'666'667, 60'000));
    assert(should_generate(true, 16'666'667, 120'000));
    assert(!should_generate(true, 8'333'333, 120'000));
    assert(!should_generate(true, 500'000'000, 60'000));
    assert(!should_generate(true, -1, 60'000));
    assert(should_generate(true, 33'333'333, 0));
    using ps5_framegen::adaptive_motion_guard;
    std::array<std::uint8_t, ps5_framegen::probe_bytes> image{};
    adaptive_motion_guard guard;
    assert(!guard.accept(image)); // seed
    assert(!guard.accept(image)); // one quiet pair
    assert(guard.accept(image));
    image.fill(255); // cut / widespread image change
    assert(!guard.accept(image));
    assert(!guard.accept(image));
    assert(guard.accept(image));
    // A translated high-contrast scene models a fast pan, even though both
    // frames have the same average brightness and histogram.
    adaptive_motion_guard pan;
    auto pan_image = image;
    auto stripes = [&](unsigned shift)
    {
        for (unsigned y = 0; y < ps5_framegen::probe_height; ++y)
            for (unsigned x = 0; x < ps5_framegen::probe_width; ++x)
                for (unsigned c = 0; c < 4; ++c)
                    pan_image[(y * ps5_framegen::probe_width + x) * 4 + c] =
                        c == 3 ? 255 : (((x + shift) / 4) % 2 ? 255 : 0);
    };
    stripes(0);
    assert(!pan.accept(pan_image)); assert(!pan.accept(pan_image)); assert(pan.accept(pan_image));
    stripes(2);
    assert(!pan.accept(pan_image)); assert(!pan.accept(pan_image)); assert(pan.accept(pan_image));
    // A concentrated small region is now rejected, even below the global gate.
    for (unsigned i = 0; i < ps5_framegen::probe_bytes / 10; ++i) image[i] = 0;
    assert(!guard.accept(image));
    assert(!guard.accept(image)); assert(guard.accept(image));
    // A high-contrast 4x4 region must be caught at every position, including
    // tile seams and all four image edges. Less than 0.2% of the preview changes.
    for (unsigned y = 0; y + 4 <= ps5_framegen::probe_height; ++y)
        for (unsigned x = 0; x + 4 <= ps5_framegen::probe_width; ++x)
        {
            adaptive_motion_guard local;
            std::array<std::uint8_t, ps5_framegen::probe_bytes> small{};
            assert(!local.accept(small)); assert(!local.accept(small)); assert(local.accept(small));
            for (unsigned dy = 0; dy < 4; ++dy)
                for (unsigned dx = 0; dx < 4; ++dx)
                    for (unsigned c = 0; c < 3; ++c)
                        small[((y + dy) * ps5_framegen::probe_width + x + dx) * 4 + c] = 255;
            assert(!local.accept(small));
            assert(!local.accept(small)); assert(local.accept(small));
        }
    adaptive_motion_guard noise;
    std::array<std::uint8_t, ps5_framegen::probe_bytes> quiet{};
    assert(!noise.accept(quiet)); assert(!noise.accept(quiet)); assert(noise.accept(quiet));
    quiet.fill(8); // low-amplitude image noise must not cause a rejection
    assert(noise.accept(quiet));
    for (unsigned i = 3; i < quiet.size(); i += 4) quiet[i] = 255;
    assert(noise.accept(quiet)); // alpha is not image motion
    quiet[0] = quiet[1] = quiet[2] = 255;
    assert(noise.accept(quiet)); // isolated bright pixel does not trip a tile
    assert(!guard.accept({})); // incomplete readback fails closed and reseeds
    assert(!guard.accept(image));
    assert(!guard.accept(image));
    assert(guard.accept(image));
}
