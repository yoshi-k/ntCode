"""Numerics experiments.

This script contains two small experiments described in `experiments/numerics.md`:

1. A simple matplotlib plot of two functions with their intersection marked.
2. A 2D heat-equation simulation on a rectangle with an X-shaped hot region,
   rendered as an animation.

Run either experiment from the command line:

    python experiments/numerics_experiment.py plot
    python experiments/numerics_experiment.py heat

By default, the script runs the plot experiment.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation


def plot_simple_functions(output_path: str = "experiments/plot1.png") -> None:
    """Create a plot of f(x)=x^2-2 and g(x)=x+2 with the intersection marked."""
    x = np.linspace(-4, 4, 400)
    f = x**2 - 2
    g = x + 2

    # Solve x^2 - 2 = x + 2 => x^2 - x - 4 = 0
    disc = 1 + 16
    x1 = (1 + math.sqrt(disc)) / 2
    x2 = (1 - math.sqrt(disc)) / 2
    y1 = x1 + 2
    y2 = x2 + 2

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(x, f, label=r"$f(x)=x^2-2$")
    ax.plot(x, g, label=r"$g(x)=x+2$")
    ax.set_xlabel(r"$x$")
    ax.set_ylabel(r"$y$")
    ax.grid(True, alpha=0.3)
    ax.legend()

    ax.scatter([x1, x2], [y1, y2], color="red", zorder=5)
    ax.annotate(
        rf"$f(x)=g(x)$\n$({x1:.3f}, {y1:.3f})$",
        xy=(x1, y1),
        xytext=(15, 15),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="->", color="red"),
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="red", alpha=0.9),
    )
    ax.annotate(
        rf"$f(x)=g(x)$\n$({x2:.3f}, {y2:.3f})$",
        xy=(x2, y2),
        xytext=(-120, -30),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="->", color="red"),
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="red", alpha=0.9),
    )

    ax.set_title("Simple plot")
    fig.tight_layout()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    print(f"Saved plot to {output}")


def _make_x_hot_mask(nx: int, ny: int, width: float = 0.08) -> np.ndarray:
    """Return an X-shaped mask over a normalized [0,1]x[0,1] grid."""
    xs = np.linspace(0.0, 1.0, nx)
    ys = np.linspace(0.0, 1.0, ny)
    X, Y = np.meshgrid(xs, ys)
    d1 = np.abs(Y - X)
    d2 = np.abs(Y - (1.0 - X))
    return (d1 < width) | (d2 < width)


def heat_equation_animation(
    output_path: str = "experiments/heat_equation.gif",
    nx: int = 600,
    ny: int = 600,
    steps: int = 300,
    # dt: float = 0.0008,
    dt: float = 1e-5,
    alpha: float = 0.01,
) -> None:
    """Simulate the 2D heat equation and save an animation as a GIF."""
    u = np.ones((ny, nx), dtype=float)
    u[_make_x_hot_mask(nx, ny)] = 5.0

    dx = 1.0 / (nx - 1)
    dy = 1.0 / (ny - 1)
    cx = alpha * dt / (dx * dx)
    cy = alpha * dt / (dy * dy)
    if cx + cy > 0.5:
        raise ValueError("Unstable parameters: reduce dt or increase grid resolution")

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(u, origin="lower", cmap="inferno", vmin=1.0, vmax=5.0, animated=True)
    ax.set_title("2D heat equation")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    plt.colorbar(im, ax=ax)

    def step(field: np.ndarray) -> np.ndarray:
        new = field.copy()
        new[1:-1, 1:-1] = (
            field[1:-1, 1:-1]
            + cx * (field[1:-1, 2:] - 2 * field[1:-1, 1:-1] + field[1:-1, :-2])
            + cy * (field[2:, 1:-1] - 2 * field[1:-1, 1:-1] + field[:-2, 1:-1])
        )
        return new

    def update(_frame_idx: int):
        nonlocal u
        u = step(u)
        im.set_array(u)
        return [im]

    anim = FuncAnimation(fig, update, frames=steps, interval=30, blit=True)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        anim.save(output, writer="pillow", dpi=120)
    finally:
        plt.close(fig)
    print(f"Saved animation to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment",
        nargs="?",
        choices=["plot", "heat"],
        default="plot",
        help="Which experiment to run",
    )
    args = parser.parse_args()

    if args.experiment == "plot":
        plot_simple_functions()
    else:
        heat_equation_animation()


if __name__ == "__main__":
    main()
