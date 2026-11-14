# T-032 — ¿sigue el comprador simulado un patrón secuencial? (solo lectura)

Desde `recsys/` (cachés en `data/`, ignorados por git; no escribe en RawTree):

    python download_user_items.py && python lfm_build.py --pull --no-write   # datos de lfm
    python explore_t032/dl_ev.py       # 10% de usuarios: eventos orgánicos de 60 días y de hoy, en orden
    python explore_t032/gen.py         # siguiente vista: Markov por producto contra popularidad de la subcategoría; embudo de compra
    python explore_t032/gen2.py        # memoria de la cadena de subcategorías (A A B -> ?)
    python explore_t032/gen3.py        # estructura producto a producto, marca y precio dentro de la subcategoría
    python explore_t032/seqfeat.py     # impresiones del carrusel propio con features de orden
    python explore_t032/evalseq.py     # cada feature de orden sobre lfm r5 fijo, corte temporal y usuarios apartados

Resultado: I-320 / E-320. Nada que desplegar.
