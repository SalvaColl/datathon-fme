"""Apply stream deltas with bounded lock batches, yielding to foreground requests."""
import time


def apply_chunks(rows, lock, apply, chunk_size=64, yield_thread=None):
    if chunk_size<1: raise ValueError('chunk_size must be positive')
    yield_thread = yield_thread or (lambda:time.sleep(0))
    begin=time.perf_counter()
    maximum=0.; chunks=0
    for start in range(0,len(rows),chunk_size):
        with lock:
            acquired=time.perf_counter()
            for row in rows[start:start+chunk_size]: apply(row)
            maximum=max(maximum,1000*(time.perf_counter()-acquired))
        chunks+=1
        if start+chunk_size<len(rows): yield_thread()
    return dict(rows=len(rows),chunks=chunks,max_lock_ms=round(maximum,2),
                elapsed_ms=round(1000*(time.perf_counter()-begin),2))
