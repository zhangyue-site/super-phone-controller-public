#include <assert.h>
#include "ota_generation.h"
int main(void) {
    atomic_uint ticket = 0;
    unsigned old = atomic_load(&ticket);
    controller_ota_cancel_ticket(&ticket);
    assert(!controller_ota_try_commit(&ticket, old)); // cancel during verification
    unsigned local = old;
    unsigned incoming = atomic_load(&ticket); // reconnect's BEGIN arrives while writer waits
    assert(controller_ota_sync_generation(&ticket, &local));
    assert(local == incoming);
    assert(!controller_ota_sync_generation(&ticket, &local)); // new BEGIN survives next iteration
    assert(controller_ota_try_commit(&ticket, incoming));
    unsigned committed = atomic_load(&ticket);
    controller_ota_cancel_ticket(&ticket);
    assert(atomic_load(&ticket) == committed); // commit boundary is irreversible
}
