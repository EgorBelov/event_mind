from app.db.base import Base
from app.db.session import engine
from app.db.models import user, event, interaction

Base.metadata.create_all(bind=engine)
exit()