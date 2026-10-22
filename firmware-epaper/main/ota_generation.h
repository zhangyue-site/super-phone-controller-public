#pragma once
#include <stdbool.h>
#include <stdatomic.h>

#define CONTROLLER_OTA_COMMIT_FLAG (1u << 31)

// Called after queue receive, before handling the received message.
static inline bool controller_ota_sync_generation(atomic_uint *ticket, unsigned *local) {
    unsigned current = atomic_load(ticket);
    if (*local == current) return false;
    *local = current;
    return true;
}
static inline bool controller_ota_try_commit(atomic_uint *ticket, unsigned generation) {
    unsigned expected = generation;
    return atomic_compare_exchange_strong(ticket, &expected, generation | CONTROLLER_OTA_COMMIT_FLAG);
}
static inline void controller_ota_cancel_ticket(atomic_uint *ticket) {
    unsigned current = atomic_load(ticket);
    while (!(current & CONTROLLER_OTA_COMMIT_FLAG) &&
           !atomic_compare_exchange_weak(ticket, &current, current + 1)) {}
}
