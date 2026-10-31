#!/usr/bin/env python3
"""Produce patch0071 without resetting the dirty WSL core source."""
from pathlib import Path
import difflib,hashlib,json
repo=Path('/mnt/c/Users/Callum/Documents/GitHub/PS5 RPCS3/KB-RPCS3')
root=Path('/home/callum/work/rpcs3-latest')
old_file=root/'rpcs3/Emu/RSX/VK/vkutils/sync.cpp'
head=root/'rpcs3/Emu/RSX/VK/vkutils/ps5_vk_fence_sleep.h'
patch=repo/'port/rpcs3-latest-patches/0071-PS5-opt-in-bounded-Vulkan-fence-wait.patch'
archive=Path('/home/callum/work/cpu-plan-vk-fence0071-original-20261031')
assert not head.exists() and not patch.exists() and not archive.exists()
old=old_file.read_text()
include='#include "sync.h"\n'
assert old.count(include)==1
new=old.replace(include,include+'#include "ps5_vk_fence_sleep.h"\n',1)
old_wait='''\t\telse
\t\t{
\t\t\twhile (auto status = vkGetFenceStatus(*g_render_device, pFence->handle))
\t\t\t{
\t\t\t\tswitch (status)
\t\t\t\t{
\t\t\t\tcase VK_NOT_READY:
\t\t\t\t\tutils::pause();
\t\t\t\t\tcontinue;
\t\t\t\tdefault:
\t\t\t\t\tdie_with_error(status);
\t\t\t\t\treturn status;
\t\t\t\t}
\t\t\t}

\t\t\treturn VK_SUCCESS;
\t\t}'''
assert new.count(old_wait)==1,("old fenced wait appears",new.count(old_wait))
new_wait='''\t\telse
\t\t{
#if defined(__PROSPERO__) && PS5_VK_FENCE_TIMED_WAIT
\t\t\tunsigned pending_polls = 0;
#endif
\t\t\twhile (auto status = vkGetFenceStatus(*g_render_device, pFence->handle))
\t\t\t{
\t\t\t\tswitch (status)
\t\t\t\t{
\t\t\t\tcase VK_NOT_READY:
#if defined(__PROSPERO__) && PS5_VK_FENCE_TIMED_WAIT
\t\t\t\t\t// This OPTIONAL policy is only for fence waits whose
\t\t\t\t\t// caller requested "infinite" completion. A fence is
\t\t\t\t\t// level-triggered; if signaled between the poll and
\t\t\t\t\t// WaitForFences, the Vulkan API returns immediately.
\t\t\t\t\t// Never treat VK_TIMEOUT as completion or lose errors.
\t\t\t\t\tif (++pending_polls >= 64)
\t\t\t\t\t{
\t\t\t\t\t\tpending_polls = 0;
\t\t\t\t\t\tconst auto result = vkWaitForFences(*g_render_device,
\t\t\t\t\t\t\t1, &pFence->handle, VK_FALSE, 100'000ull);
\t\t\t\t\t\tif (result == VK_SUCCESS)
\t\t\t\t\t\t\treturn VK_SUCCESS;
\t\t\t\t\t\tif (result != VK_TIMEOUT)
\t\t\t\t\t\t{
\t\t\t\t\t\t\tdie_with_error(result);
\t\t\t\t\t\t\treturn result;
\t\t\t\t\t\t}
\t\t\t\t\t\tcontinue;
\t\t\t\t\t}
#endif
\t\t\t\t\tutils::pause();
\t\t\t\t\tcontinue;
\t\t\t\tdefault:
\t\t\t\t\tdie_with_error(status);
\t\t\t\t\treturn status;
\t\t\t\t}
\t\t\t}

\t\t\treturn VK_SUCCESS;
\t\t}'''
new=new.replace(old_wait,new_wait,1)
header='''#pragma once
// CPU optimisation plan, Section 2: PS5 Vulkan zero-timeout fence policy.
// Deliberately OFF by default. The original busy-poll path remains
// completely unchanged in normal PS5/desktop builds.
//
// When separately enabled in a diagnostic build, after 64 VK_NOT_READY
// polls, let the Vulkan driver block for up to 100 microseconds.
// This is not approved as a production default until sustained A/B/A
// gameplay verifies p95/p99, device loss and shutdown behaviour.
#ifndef PS5_VK_FENCE_TIMED_WAIT
#define PS5_VK_FENCE_TIMED_WAIT 0
#endif
#if PS5_VK_FENCE_TIMED_WAIT != 0 && PS5_VK_FENCE_TIMED_WAIT != 1
#error PS5_VK_FENCE_TIMED_WAIT must be 0 or 1
#endif
'''
archive.mkdir()
(archive/'sync.cpp').write_text(old)
(archive/'manifest.json').write_text(json.dumps({
 'patch':71,'old_sha256':hashlib.sha256(old.encode()).hexdigest(),
 'new_sha256':hashlib.sha256(new.encode()).hexdigest(),
 'header_sha256':hashlib.sha256(header.encode()).hexdigest()},indent=2)+'\n')
old_file.write_text(new)
head.write_text(header)
diff=[]
for relative,a,b in [('rpcs3/Emu/RSX/VK/vkutils/sync.cpp',old,new),
                      ('rpcs3/Emu/RSX/VK/vkutils/ps5_vk_fence_sleep.h','',header)]:
 diff.append(f'diff --git a/{relative} b/{relative}\n')
 if not a:diff.append('new file mode 100644\n')
 diff.extend(difflib.unified_diff(a.splitlines(True),b.splitlines(True),
   fromfile='a/'+relative if a else '/dev/null',tofile='b/'+relative,n=4))
patch.write_text('''From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: KB <kb@kb-rpcs3.example>
Date: Sat, 31 Oct 2026 03:42:00 +0000
Subject: [PATCH] PS5: opt-in bounded Vulkan fence wait for CPU plan

Default OFF keeps existing zero-timeout busy poll byte-for-byte.
Explicit diagnostic ON polls 64 statuses then issues a 100us Vulkan
wait, preserving level-triggered completion, timeouts and errors.
No new guest synchronization or production behavior change.
---
'''+''.join(diff))
print('PASS patch0071 created',patch,'bytes',patch.stat().st_size)
