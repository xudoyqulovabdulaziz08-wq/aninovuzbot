# database/repository.py
from sqlalchemy import select
from database.models import DBUser

class UserRepository:
    @staticmethod
    async def get_or_create(session, user_obj):
        result = await session.execute(select(DBUser).where(DBUser.user_id == user_obj.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            db_user = DBUser(user_id=user_obj.id, username=user_obj.username, status="user")
            session.add(db_user)
        elif db_user.username != user_obj.username:
            db_user.username = user_obj.username
        await session.commit()
        return db_user