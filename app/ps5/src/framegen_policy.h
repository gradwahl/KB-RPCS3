// Presentation cadence only; never changes PS3 clocks or guest frame limits.
// SPDX-License-Identifier: MIT
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <span>
namespace ps5_framegen
{
inline constexpr std::uint32_t probe_width = 128, probe_height = 72;
inline constexpr std::uint32_t probe_bytes = probe_width * probe_height * 4;

// Conservative image-change proxy, not an optical-flow confidence estimate.
// Global pans/cuts and concentrated local changes reject the entire midpoint.
// Overlapping tiles avoid blind spots at tile boundaries. This is still a
// source-image difference heuristic, not detection of actual neural artifacts.
// Two quiet pairs are required after a rejection to avoid rapid switching.
class adaptive_motion_guard
{
    std::array<std::uint8_t, probe_bytes> previous{};
    bool seeded{};
    unsigned quiet_pairs{};

public:
    bool accept(std::span<const std::uint8_t> rgba)
    {
        if (rgba.size() != previous.size()) { seeded = false; quiet_pairs = 0; return false; }
        std::uint32_t sum = 0, changed = 0, strong = 0;
        std::array<std::uint16_t, probe_width * probe_height> differences{};
        for (std::size_t i = 0; i < rgba.size(); i += 4)
        {
            unsigned difference = 0;
            for (unsigned c = 0; c < 3; ++c)
            {
                const int delta = int(rgba[i + c]) - int(previous[i + c]);
                difference += unsigned(delta < 0 ? -delta : delta);
            }
            sum += difference;
            differences[i / 4] = static_cast<std::uint16_t>(difference);
            changed += difference >= 24 * 3;
            strong += difference >= 64 * 3;
        }
        const bool was_seeded = seeded;
        std::copy(rgba.begin(), rgba.end(), previous.begin());
        seeded = true;
        constexpr auto pixels = probe_width * probe_height;
        const bool large_change = (sum >= pixels * 18 * 3 && changed * 100 >= pixels * 30) ||
            strong * 100 >= pixels * 35;
        bool local_change = false;
        constexpr unsigned tile = 8, stride = 4, tile_pixels = tile * tile;
        static_assert((probe_width - tile) % stride == 0 && (probe_height - tile) % stride == 0);
        for (unsigned y = 0; y + tile <= probe_height && !local_change; y += stride)
            for (unsigned x = 0; x + tile <= probe_width && !local_change; x += stride)
            {
                unsigned tile_sum = 0, tile_changed = 0, tile_strong = 0;
                for (unsigned dy = 0; dy < tile; ++dy)
                    for (unsigned dx = 0; dx < tile; ++dx)
                    {
                        const auto difference = differences[(y + dy) * probe_width + x + dx];
                        tile_sum += difference;
                        tile_changed += difference >= 24 * 3;
                        tile_strong += difference >= 64 * 3;
                    }
                local_change = (tile_sum >= tile_pixels * 24 * 3 && tile_changed * 100 >= tile_pixels * 40) ||
                    tile_strong * 100 >= tile_pixels * 25;
            }
        if (!was_seeded || large_change || local_change) { quiet_pairs = 0; return false; }
        if (quiet_pairs < 2) ++quiet_pairs;
        return quiet_pairs >= 2;
    }
};

// Skip cold start, pauses and output already near the display refresh rate.
// One midpoint needs two refresh slots; do not queue synthetic work at 60->60.
inline bool should_generate(bool history, std::int64_t interval_ns, std::uint32_t refresh_millihz)
{
    const auto refresh_ns = 1'000'000'000'000ll / (refresh_millihz ? refresh_millihz : 60'000);
    return history && interval_ns >= refresh_ns * 18 / 10 && interval_ns <= 100'000'000;
}
}
