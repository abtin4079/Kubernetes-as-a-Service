from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()

def get_db_connection():
    conn = psycopg2.connect(
        host="postgresql-slave.default.svc.cluster.local",  # Ensure this matches your PostgreSQL slave service name
        database="yourdatabase",
        user="mydbuser",
        password="mypassword"
    )
    return conn

@app.get('/health/{app_name}')
async def get_health(app_name: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM health_status WHERE app_name = %s', (app_name,))
        health_status = cur.fetchall()
        cur.close()
        conn.close()
        if not health_status:
            raise HTTPException(status_code=404, detail="App not found")
        return JSONResponse(content=health_status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5000)
