import asyncio
import structlog
from config import config
from robot_agent import RobotAgent
from rich.console import Console
from rich.table import Table
from rich.live import Live

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)
console = Console()

async def display_status_grid(robots: list[RobotAgent]) -> None:
    """Uses rich live display to print active robot fleet stats."""
    table = Table(title="🤖 Warehouse Audit Platform - Robot Simulator Fleet")
    table.add_column("Robot ID", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Battery %", style="green")
    table.add_column("Position (X, Y, Z)", style="yellow")
    table.add_column("Active Mission", style="blue")
    table.add_column("Network", style="white")

    for r in robots:
        status_text = r.state.status
        battery_text = f"{r.state.battery_pct:.1f}%"
        pos_text = f"({r.state.current_x:.2f}, {r.state.current_y:.2f}, {r.state.current_z:.2f})"
        mission_text = r.state.mission_id or "N/A"
        net_text = "[green]CONNECTED[/]" if r.connected else "[red]OFFLINE (Dead Zone)[/]"
        
        table.add_row(r.state.robot_id, status_text, battery_text, pos_text, mission_text, net_text)

    console.clear()
    console.print(table)

async def main():
    logger.info("simulator_startup", target_robot_count=config.ROBOT_COUNT)
    
    # Initialize agents
    robots = [
        RobotAgent(robot_id=f"robot-{i:03d}", warehouse_id=config.WAREHOUSE_ID)
        for i in range(1, config.ROBOT_COUNT + 1)
    ]
    
    for r in robots:
        await r.initialize()
        asyncio.create_task(r.run())

    # Live dashboard loops
    while True:
        await display_status_grid(robots)
        await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("simulator_shutdown")
