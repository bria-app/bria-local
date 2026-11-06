# Datos de prueba

Son **datos sintéticos de una simulación controlada**. Los diseñamos para ejercitar el sistema de punta a punta. No pertenecen a ninguna tienda real, y los nombres, documentos y marcas que aparecen son solo ejemplos. No sirven como evidencia de la precisión del pronóstico en un negocio real.

## Lo que se carga solo

### PetHouse Miraflores: la base de las pruebas

La carga [`semillas/seed_pethouse_miraflores.py`](semillas/seed_pethouse_miraflores.py) la primera vez que se levanta el sistema. Es la tienda de las capturas del manual. Trae dueño, vendedora, plan Premium, 3 proveedores y operación diaria desde el 1 de mayo de 2024 hasta ayer. Cada producto pone a prueba un comportamiento distinto:

| Código | Producto | Comportamiento |
|---|---|---|
| SKU-201 | Arena para gatos 10 kg | Estable, con crecimiento leve y una semana de promoción en julio de 2025 |
| SKU-202 | Croquetas perro adulto 15 kg | Crece, tiene diciembre fuerte y 3 compras grandes de un albergue |
| SKU-203 | Pipeta antipulgas | Estacional: se vende el triple en verano que en invierno |
| SKU-204 | Comida húmeda gato 85 g | Alto volumen: creció rápido en 2025 y luego se estabilizó |
| SKU-205 | Snack dental perro | Producto nuevo, lanzado en julio de 2026 |
| SKU-206 | Shampoo hipoalergénico | Estable hasta marzo de 2026; desde abril vende 40 % menos |
| SKU-207 | Casaca polar para perro | Solo se vende en invierno |
| SKU-208 | Placa de identificación | Intermitente: muchos días sin venta |
| SKU-209 | Cama ortopédica | Esporádica, con pedidos grandes de una clínica |
| SKU-210 | Alimento cachorro 3 kg | Crece parejo, pero el proveedor falló 3 veces y hubo ventas perdidas |

La semilla también genera los 3 meses siguientes sin cargarlos en la base, y los guarda con la demanda esperada de cada día en `semillas/verdad_pethouse_miraflores.json`. Ese archivo permite comparar un pronóstico contra lo que se sabe que iba a pasar en esta simulación.

### PetHouse Lima: la segunda empresa

La carga la API al arrancar, con `scripts/bootstrap_demo.py`. Trae 12 productos (SKU-001 a SKU-012) con códigos de barras válidos para probar el lector en caja, y ventas desde 2022 hasta ayer. Sirve para comprobar que una empresa no ve los datos de otra.

## Lo que se sube desde la aplicación

Están en [`importables/`](importables). Conviene subirlos en una cuenta nueva, para que no se mezclen con las tiendas anteriores.

| Archivo | Contenido | Dónde se carga |
|---|---|---|
| `mype-2026/1_inventario_pethouse_sep2026.xlsx` | Inventario de 48 productos, con título arriba y columnas propias | **Inventario › Importar** |
| `mype-2026/2_ventas_pethouse_jun-sep2026.xlsx` | 200 líneas de venta, con una fila TOTAL al final que debe salir como error | **Ventas › Historial importado › Importar ventas** |
| `perfiles-demo/inventario_*.xlsx` y `ventas_*.xlsx` | Inventario y ventas de 5 tipos de tienda: calzado de cuero, perfumes, productos Apple, ropa vintage y skincare | Los mismos dos lugares |
| `historia-csv/productos.csv` y `ventas.csv` | Catálogo de 12 productos y 13,152 ventas diarias de 2022 a 2024 | Los mismos dos lugares |

Sube primero el inventario y luego las ventas, porque las ventas se enlazan con los productos por su código.
